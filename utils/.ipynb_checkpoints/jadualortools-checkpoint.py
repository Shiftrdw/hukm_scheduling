from ortools.sat.python import cp_model
from utils.timeslots import parse_ISO8601_date_to_datetime
from utils.appsync import query, timeslotsByTenantId
from itertools import product
import pandas as pd
import datetime
import utils.utils as utils
import random
import logging

log = logging.getLogger(__name__)


def negated_bounded_span(works, start, length):
    """Filters an isolated sub-sequence of variables assined to True.
    Extract the span of Boolean variables [start, start + length), negate them,
    and if there is variables to the left/right of this span, surround the span by
    them in non negated form.
    Args:
    works: a list of variables to extract the span from.
    start: the start to the span.
    length: the length of the span.
    Returns:
    a list of variables which conjunction will be false if the sub-list is
    assigned to True, and correctly bounded by variables assigned to False,
    or by the start or end of works.
    """
    sequence = []
    # Left border (start of works, or works[start - 1])
    if start > 0:
        sequence.append(works[start - 1])
    for i in range(length):
        sequence.append(works[start + i].Not())
    # Right border (end of works or works[start + length])
    if start + length < len(works):
        sequence.append(works[start + length])
    return sequence


def add_soft_sequence_constraint(model, works, hard_min, soft_min, min_cost,
                                    soft_max, hard_max, max_cost, prefix):
    """Sequence constraint on true variables with soft and hard bounds.
    This constraint look at every maximal contiguous sequence of variables
    assigned to true. If forbids sequence of length < hard_min or > hard_max.
    Then it creates penalty terms if the length is < soft_min or > soft_max.
    Args:
    model: the sequence constraint is built on this model.
    works: a list of Boolean variables.
    hard_min: any sequence of true variables must have a length of at least
        hard_min.
    soft_min: any sequence should have a length of at least soft_min, or a
        linear penalty on the delta will be added to the objective.
    min_cost: the coefficient of the linear penalty if the length is less than
        soft_min.
    soft_max: any sequence should have a length of at most soft_max, or a linear
        penalty on the delta will be added to the objective.
    hard_max: any sequence of true variables must have a length of at most
        hard_max.
    max_cost: the coefficient of the linear penalty if the length is more than
        soft_max.
    prefix: a base name for penalty literals.
    Returns:
    a tuple (variables_list, coefficient_list) containing the different
    penalties created by the sequence constraint.
    """
    cost_literals = []
    cost_coefficients = []

    # Forbid sequences that are too short.
    for length in range(1, hard_min):
        for start in range(len(works) - length + 1):
            model.AddBoolOr(negated_bounded_span(works, start, length))

    # Penalize sequences that are below the soft limit.
    if min_cost > 0:
        for length in range(hard_min, soft_min):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                name = ': under_span(start=%i, length=%i)' % (start, length)
                lit = model.NewBoolVar(prefix + name)
                span.append(lit)
                model.AddBoolOr(span)
                cost_literals.append(lit)
                # We filter exactly the sequence with a short length.
                # The penalty is proportional to the delta with soft_min.
                cost_coefficients.append(min_cost * (soft_min - length))

    # Penalize sequences that are above the soft limit.
    if max_cost > 0:
        for length in range(soft_max + 1, hard_max + 1):
            for start in range(len(works) - length + 1):
                span = negated_bounded_span(works, start, length)
                name = ': over_span(start=%i, length=%i)' % (start, length)
                lit = model.NewBoolVar(prefix + name)
                span.append(lit)
                model.AddBoolOr(span)
                cost_literals.append(lit)
                # Cost paid is max_cost * excess length.
                cost_coefficients.append(max_cost * (length - soft_max))

    # Just forbid any sequence of true variables with length hard_max + 1
    for start in range(len(works) - hard_max):
        model.AddBoolOr(
            [works[i].Not() for i in range(start, start + hard_max + 1)])
    return cost_literals, cost_coefficients


def add_soft_sum_constraint(model, works, hard_min, soft_min, min_cost,
                            soft_max, hard_max, max_cost, prefix):
    """Sum constraint with soft and hard bounds.
    This constraint counts the variables assigned to true from works.
    If forbids sum < hard_min or > hard_max.
    Then it creates penalty terms if the sum is < soft_min or > soft_max.
    Args:
    model: the sequence constraint is built on this model.
    works: a list of Boolean variables.
    hard_min: any sequence of true variables must have a sum of at least
        hard_min.
    soft_min: any sequence should have a sum of at least soft_min, or a linear
        penalty on the delta will be added to the objective.
    min_cost: the coefficient of the linear penalty if the sum is less than
        soft_min.
    soft_max: any sequence should have a sum of at most soft_max, or a linear
        penalty on the delta will be added to the objective.
    hard_max: any sequence of true variables must have a sum of at most
        hard_max.
    max_cost: the coefficient of the linear penalty if the sum is more than
        soft_max.
    prefix: a base name for penalty variables.
    Returns:
    a tuple (variables_list, coefficient_list) containing the different
    penalties created by the sequence constraint.
    """
    cost_variables = []
    cost_coefficients = []
    sum_var = model.NewIntVar(hard_min, hard_max, '')
    # This adds the hard constraints on the sum.
    model.Add(sum_var == sum(works))

    # Penalize sums below the soft_min target.
    if soft_min > hard_min and min_cost > 0:
        delta = model.NewIntVar(-len(works), len(works), '')
        model.Add(delta == soft_min - sum_var)
        # TODO(user): Compare efficiency with only excess >= soft_min - sum_var.
        excess = model.NewIntVar(0, 7, prefix + ': under_sum')
        model.AddMaxEquality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(min_cost)

    # Penalize sums above the soft_max target.
    if soft_max < hard_max and max_cost > 0:
        delta = model.NewIntVar(-7, 7, '')
        model.Add(delta == sum_var - soft_max)
        excess = model.NewIntVar(0, 7, prefix + ': over_sum')
        model.AddMaxEquality(excess, [delta, 0])
        cost_variables.append(excess)
        cost_coefficients.append(max_cost)

    return cost_variables, cost_coefficients

class JadualModel():

    def __init__(
        self, 
        workers_list, 
        workers_roles, 
        requests_data, 
        date_list, 
        duty_id_for_dates, 
        duty_types,
        leave_types,
        leaves_id_for_dates, 
        df, 
        transition_rules, 
        off_day,
        off_day_date_list,
        tenant_id,
        sum_constraints,
        sequence_constraints
    ):
        self.workers_list = random.sample(workers_list, len(workers_list))
        self.number_of_workers = len(self.workers_list)
        self.workers_roles = workers_roles
        self.date_list = date_list
        self.duty_id_for_dates = duty_id_for_dates
        self.leaves_id_for_dates = leaves_id_for_dates
        self.duty_types = duty_types
        self.leave_types = leave_types
        self.leaves_dependent_on_shift = []
        self.off_day = off_day
        self.off_day_id = off_day["id"]
        self.off_day_date_list = off_day_date_list
        self.timeslots = []
        self.df = df
        self.requests = requests_data
        self.transition_rules = transition_rules
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.work = {}
        self.schedule_data = {}
        self.request_list = []
        self.obj_bool_vars_min = []
        self.obj_bool_coeffs_min = []
        self.obj_int_vars = []
        self.obj_int_coeffs = []
        self.date_prior_list = []
        self.timeslot_list = []
        self.tenant_id = tenant_id
        self.sum_constraints = sum_constraints
        self.sequence_constraints = sequence_constraints

    def get_functions_dict(self):
        return {
            "one_worker_one_shift": self.one_worker_one_shift,
            "match_worker_role_and_shift_hard": self.match_worker_role_and_shift_hard,
            'generate_transition_rules_model': self.generate_transition_rules_model,
            'fairness_allocation': self.fairness_allocation,
            'minimize_bools': self.minimize,
            "number_workers_per_shift": self.number_workers_per_shift,
            "number_off_day_per_worker_per_roster": self.number_off_day_per_worker_per_roster,
            "maximize_workers_per_shift": self.maximize_workers_per_shift,
            "minimize_off_days": self.minimize_off_days,
            "maximize_off_days": self.maximize_off_days,
            "populate_requests": self.populate_requests,
            "maximize_excess_covers": self.excess_covers
        }

    def create_model_duties(self):
        for w in self.workers_list:
            for d in self.date_list:
                for s in self.duty_id_for_dates[d]:
                    self.work[(w, d, s)] = self.model.NewBoolVar(f'work_{w}_{d}_{s}')
    
    def create_model_leaves(self):
        for w in self.workers_list:
            for d in self.date_list:
                # ignored if no leaves variable
                for l in self.leaves_id_for_dates[d]:
                    self.work[(w, d, l)] = self.model.NewBoolVar(f'work_{w}_{d}_{l}')
    
        for d in self.date_list:
            for l in self.leaves_id_for_dates[d]:
                self.model.Add(sum(self.work[(w, d, l)] for w in self.workers_list) >= 0)
                
# ------------------------------------------------------------------------------------------------------------
# Previous roster - takes into account the previous roster based on transition days

# [{'sequence': [{'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 0}, {'type':'', 'id': '', 'day': 2}, {'type': 'duty', 'id': 'OFF_DAY', 'day': 2}], 'cost': 4, 'strategy': 'max'}, {'sequence': [{'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 0}, {'type':'shift', 'id':'21c993d9-b088-45b1-b859-d53f019cc94e', 'day': 1}], 'cost': 0, 'strategy': 'never'}, {'sequence': [{'type':'shift', 'id':'21c993d9-b088-45b1-b859-d53f019cc94e', 'day': 0}, {'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 1}], 'cost': 0, 'strategy': 'never'}]

# test strategy - count days prior, -1 from the max transition len. if date start at x, date prior range start at and ends before (hence -1).

# initially need to add to model space.
# for date range, add new bool var

# for s in self.duty_id_for_dates[d]:
#     self.work[(w, d, s)] = self.model.NewBoolVar(f'work_{w}_{d}_{s}')

# # ignored if no leaves variable
# for l in self.leaves_id_for_dates[d]:
#     self.work[(w, d, l)] = self.model.NewBoolVar(f'work_{w}_{d}_{l}')

# then
# for each timeslots
# self.model.Add(self.work[(workerid, date, slotid)] == 1)

# need to check if date in range

# ------------------------------------------------------------------------------------------------------------

    def init_previous_roster_model(self, max_len_transition_rules):
        days_prior_to_consider = 14
        date_prior_start = self.date_list[0] - datetime.timedelta(days=days_prior_to_consider)
        date_prior_end = self.date_list[0] - datetime.timedelta(days=1)
        self.date_prior_list = [date_prior_start + datetime.timedelta(days=x) for x in range(days_prior_to_consider)]
        
        print(date_prior_start)
        print(days_prior_to_consider)
        print(self.date_prior_list)
        
        for w in self.workers_list:
            for d in self.date_prior_list:
                for s in self.duty_types:
                    self.work[(w, d, s)] = self.model.NewBoolVar(f'work_{w}_{d}_{s}')
                    
                # ignored if no leaves variable
                for l in self.leave_types:
                    self.work[(w, d, l)] = self.model.NewBoolVar(f'work_{w}_{d}_{l}')
    
    def get_prior_timeslots(self):
        start_date = self.date_prior_list[0].strftime('%Y-%m-%d')
        try:
            end_date = self.date_prior_list[-1].strftime('%Y-%m-%d')
        except Exception as e:
            end_date = start_date
        print(f'we are considering date from {start_date} to {end_date}')
        params_timeslots = {'tenantId': self.tenant_id, 'between': [f"{start_date}", f"{end_date}"]}
        timeslots_data = query(timeslotsByTenantId, params_timeslots)
        self.timeslot = timeslots_data["timeslotsByTenantId"]["items"]
        self.generate_timeslot_list()
        
    def generate_timeslot_list(self):
        for timeslot in self.timeslots:
            worker_ts = timeslot["workerId"]
            date_ts = datetime.strptime(timeslot["start"], '%Y-%m-%d').date()
            if timeslot["type"] == "Duty":
                timeslot_ref = (worker_ts, date_ts, timeslot["dutyId"])
            elif timeslot["type"] == "Leave":
                timeslot_ref = (worker_ts, date_ts, timeslot["leaveId"])
            self.timeslot_list.append(timeslot_ref)
            
    def timeslot_match(self, _timeslot):
        return _timeslot in self.timeslot_list
        
    def add_timeslots_to_model(self):
        for w in self.workers_list:
            for d in self.date_prior_list:
                for s in self.duty_types:
                    if self.timeslot_match((w, d, s)):
                        self.model.Add(self.work[(w, d, s)] == 1)
                    else:
                        self.model.Add(self.work[(w, d, s)] == 0)
                for l in self.leave_types:
                    if self.timeslot_match((w, d, l)):
                        self.model.Add(self.work[(w, d, l)] == 1)
                    else:
                        self.model.Add(self.work[(w, d, l)] == 0)
                            
    def build_previous_roster(self):
        if self.transition_rules:
            max_len_transition_rules = max(len(rule_set["sequence"]) for rule_set in self.transition_rules)
            if max_len_transition_rules > 0:
                self.init_previous_roster_model(max_len_transition_rules)
                self.get_prior_timeslots()
                self.add_timeslots_to_model()
                
    def use_current_selected_roster(self, selected_roster=None):
        if selected_roster is None:
            selected_roster = []
        for slot in selected_roster:
            # s = slot["leave_id"] if slot["type"] == "Leave" else slot["duty_id"]
            w = slot["worker_id"]
            d = slot["start"]
            if slot["type"] == "Leave":
                for l in self.leave_types:
                    try:
                        self.model.Add(self.work[(w, d, l)] == 0)
                    except Exception as e:
                        pass
            else:
                for s in self.duty_types:
                    try:
                        self.model.Add(self.work[(w, d, s)] == 0)
                    except Exception as e:
                        pass
                    
                
# ------------------------------------------------------------------------------------------------------------
#  Shift continuous sequences
# ------------------------------------------------------------------------------------------------------------

    # Shift constraints on continuous sequence :
    #     (shift, hard_min, soft_min, min_penalty,
    #             soft_max, hard_max, max_penalty)
    # shift_constraints = [
    #     # One or two consecutive days of rest, this is a hard constraint.
    #     (0, 1, 1, 0, 2, 2, 0),
    #     # between 2 and 3 consecutive days of night shifts, 1 and 4 are
    #     # possible but penalized.
    #     (3, 1, 2, 20, 3, 4, 5),
    # ]
    
    # need to add a new tenant data model for continuous sequences. NEED TO HAVE TYPE LA
    def implement_slot_sequence_constraints(self, duties_by_shift):
        print('implementing slot sequence constraints')
        for seq_constraint in self.sequence_constraints or []:
            slot_id = seq_constraint["slotId"]
            slot_type = seq_constraint["slotType"]
            hard_min = seq_constraint["hardMin"]
            soft_min = seq_constraint["softMin"]
            min_cost = seq_constraint["minCost"]
            soft_max = seq_constraint["softMax"]
            hard_max = seq_constraint["hardMax"]
            max_cost = seq_constraint["maxCost"]

            duties = duties_by_shift[slot_id] if slot_type == "Shift" else [slot_id]

            for w in self.workers_list:
                works = []
                for d in self.date_list:
                    for s in duties:
                        try:
                            works.append(self.work[(w, d, s)])
                        except Exception as e:
                            print(e)
                
                try:
                    variables, coeffs = add_soft_sequence_constraint(
                        self.model,
                        works,
                        hard_min,
                        soft_min,
                        min_cost,
                        soft_max,
                        hard_max,
                        max_cost,
                        f'sequence_constraint({w}, {slot_id})')
                    self.obj_bool_vars_min.extend(variables)
                    self.obj_bool_coeffs_min.extend(coeffs)
                except Exception as e:
                    print(e)

# ------------------------------------------------------------------------------------------------------------
#  Soft and hard sum sequences
# ------------------------------------------------------------------------------------------------------------   
    
    # need array of sum constraints -> in there need to specify weekly or monthly
    # self.array_of sum constraints = [{ shift, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost, frequency': 'week @ month'}]
    # dilemma - if monthly, need to adjust weekly.
    # date untuk particular shift tu?? - done via dict
    # if monthly for d in range datelist len of 1 month - combine date list prior? - just 2 weeks of prior. list prior + date_list -> then full date list. works can iterate over this
    # if weekly, group dates in array of weeks and iterate of each array. - ? can use chunk, but need to see duty's daily/weekday/weekend things - need this info in the constraint array
    # if weekly, use same date list prior+datelist. chunk by weeks. use try catch to simplify
    def implement_sum_constraint(self):
        all_dates = self.date_prior_list + self.date_list
        print('to do sum constraints, this is all dates', all_dates)
        for sum_const in self.sum_constraints: # need to build data model
            slot_id = sum_const["slotId"]
            hard_min = sum_const["hardMin"]
            soft_min = sum_const["softMin"]
            min_cost = sum_const["minCost"]
            soft_max = sum_const["softMax"]
            hard_max = sum_const["hardMax"]
            max_cost = sum_const["maxCost"]
            sum_type = sum_const["type"]
            slot_type = sum_const["slotType"]
            if slot_type == "Duty":
                duties = [slot_id]
            else:
                duties = utils.filter_duties_by_shift(self.df, slot_id)
            for w in self.workers_list:
                if sum_type == "MONTH":
                    self.sum_constraint(
                        w, 
                        duties,
                        all_dates,
                        '1_month',
                        hard_min, 
                        soft_min, 
                        min_cost, 
                        soft_max,
                        hard_max, 
                        max_cost
                    )
                else:
                    weeks = utils.chunk(all_dates, 7)
                    for index, week in enumerate(weeks):
                        self.sum_constraint(
                            w, 
                            duties,
                            week,
                            index,
                            hard_min, 
                            soft_min, 
                            min_cost, 
                            soft_max,
                            hard_max, 
                            max_cost
                        )
                            
    def sum_constraint(
        self,
        w, 
        duties, 
        date_list, 
        date_list_index,
        hard_min, 
        soft_min, 
        min_cost, 
        soft_max,
        hard_max, 
        max_cost
    ):
        try:
            works = [self.work[w, duty, d] for duty in duties for d in date_list]
            prefix = f'weekly_sum_constraint({w}, {duties}, {date_list_index})'
            variables, coeffs = add_soft_sum_constraint(
                self.model, 
                works, 
                hard_min, 
                soft_min, 
                min_cost, 
                soft_max,
                hard_max, 
                max_cost, 
                prefix
            )
            self.obj_int_vars.extend(variables)
            self.obj_int_coeffs.extend(coeffs)
        except Exception as e:
            print(e)
# ------------------------------------------------------------------------------------------------------------
# OFFDAY
# ------------------------------------------------------------------------------------------------------------
                    
    def create_offdays(self):
        for w in self.workers_list:
            for d in self.off_day_date_list:
                self.work[(w, d, self.off_day_id)] = self.model.NewBoolVar(f'work_{w}_{d}_{self.off_day_id}')
    
    def number_off_day_per_worker_per_roster(self, params = None):
        if params is None:
            params = [0,1]
        print('generating off day rules')
        # self.create_offdays()
        
        min_per_week, max_per_week = params[0], params[1]
        for w in self.workers_list:
            if self.off_day['daily']:
                for a_week in utils.chunk(self.off_day_date_list, 7):
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) <= max_per_week)
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) >= min_per_week)
            elif self.off_day["weekend"]:
                _off_day_date_list = utils.group_dates_by_weekend(self.off_day_date_list)
                _off_day_by_week = utils.remove_duplicates(_off_day_date_list)
                for a_week in _off_day_by_week:
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) <= max_per_week)
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) >= min_per_week)
            elif self.off_day["weekday"]:
                for a_week in utils.chunk(self.off_day_date_list, 5):
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) <= max_per_week)
                    self.model.Add(sum(self.work[(w, d, self.off_day_id)] for d in a_week) >= min_per_week)

    def minimize_off_days(self):
        for w in self.workers_list:
            if self.off_day['daily']:
                for a_week in utils.chunk(self.off_day_date_list, 7):
                    self.model.Minimize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
            elif self.off_day["weekend"]:
                _off_day_date_list = utils.group_dates_by_weekend(self.off_day_date_list)
                _off_day_by_week = utils.remove_duplicates(_off_day_date_list)
                for a_week in _off_day_by_week:
                    self.model.Minimize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
            elif self.off_day["weekday"]:
                for a_week in utils.chunk(self.off_day_date_list, 5):
                    self.model.Minimize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
            
    def maximize_off_days(self):
        for w in self.workers_list:
            if self.off_day['daily']:
                for a_week in utils.chunk(self.off_day_date_list, 7):
                    self.model.Maximize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
            elif self.off_day["weekend"]:
                _off_day_date_list = utils.group_dates_by_weekend(self.off_day_date_list)
                _off_day_by_week = utils.remove_duplicates(_off_day_date_list)
                for a_week in _off_day_by_week:
                    self.model.Maximize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
            elif self.off_day["weekday"]:
                for a_week in utils.chunk(self.off_day_date_list, 5):
                    self.model.Maximize(sum(self.work[(w, d, self.off_day_id)] for d in a_week))
                    
# ------------------------------------------------------------------------------------------------------------
# Fairness
# ------------------------------------------------------------------------------------------------------------

    def fairness_allocation(self):
        fairshift = {}
        sum_of_shifts = {}
        num_days = len(self.date_list) 
        for w in self.workers_list:
            for s in self.duty_types:
                sum_of_shifts[(w, s)] = self.model.NewIntVar(0, num_days, f'sum_of_shifts_{w}_{s}')
                shift_list = []
                for d in self.date_list:
                    try:
                        shift_list.append(self.work[(w, d, s)])
                    except Exception as e:
                        pass
                self.model.Add(sum_of_shifts[(w, s)] == sum(shift_list))
                                
        for s in self.duty_types:
            try:
                min_fair_shift = self.model.NewIntVar(0, num_days, f'min_fair_shift_{s}')
                max_fair_shift = self.model.NewIntVar(0, num_days, f'max_fair_shift_{s}')
                self.model.AddMinEquality(min_fair_shift, [sum_of_shifts[(w, s)] for w in self.workers_list])
                self.model.AddMaxEquality(max_fair_shift, [sum_of_shifts[(w, s)] for w in self.workers_list]) 

                self.model.Add(max_fair_shift - min_fair_shift <= 1)

            except Exception as e:
                pass
                
# ------------------------------------------------------------------------------------------------------------
# 1 worker 1 shift
# ------------------------------------------------------------------------------------------------------------
            
    # def one_shift_one_worker(self):
    #     for d in self.date_list:
    #         for s in self.duty_id_for_dates[d]:
    #             self.model.AddExactlyOne(self.work[(w, d, s)] for w in self.workers_list)

    def one_worker_one_shift_duty(self):
        """constraint each worker only work 1 day 1 shift"""
        print("constraint each worker only work 1 day 1 shift")
        for w in self.workers_list:
            for d in self.date_list:
                all_slot_variables = []
                all_slot_variables.extend(self.duty_id_for_dates[d])
                self.model.AddAtMostOne(self.work[(w, d, s)] for s in all_slot_variables)
    
    def one_worker_one_shift(self):
        """constraint each worker only work 1 day 1 shift"""
        print("constraint each worker only work 1 day 1 shift")
        for w in self.workers_list:
            for d in self.date_list:
                all_slot_variables = []
                all_slot_variables.extend(self.leaves_id_for_dates[d])
                all_slot_variables.extend(self.duty_id_for_dates[d])
                self.model.AddAtMostOne(self.work[(w, d, s)] for s in all_slot_variables)

# ------------------------------------------------------------------------------------------------------------
# Roles
# ------------------------------------------------------------------------------------------------------------

    def match_worker_role_and_shift_hard(self):
        """constraint to match role with shift. create an intermediate variable and enforce if"""
        print("constraint to match role with shift. create an intermediate variable and enforce if")
        for w in self.workers_list:
            for d in self.date_list:
                for s in self.duty_id_for_dates[d]:
                    try:
                        duty_role = utils.query_df(self.df, d, s, 'role_id')
                        if duty_role not in self.workers_roles[w]:
                            self.model.Add(self.work[(w, d, s)] == 0)
                    except:
                        log.info("slot has no duty")
    
    def match_worker_role_and_shift_soft(self):
        int_role_no_match_vars = {}
        for w in self.workers_list:
            for d in self.date_list:
                for s in self.duty_id_for_dates[d]:
                    duty_role = utils.query_df(self.df, d, s, 'role_id')
                    if duty_role not in self.workers_roles[w]:
                        int_role_no_match_vars[(w, d, s)] = self.model.NewBoolVar(f'role_{w}_{d}_{s}')
                        self.model.Add(self.work[(w, d, s)] == 0).OnlyEnforceIf(int_role_no_match_vars[(w, d, s)])
                        
# ------------------------------------------------------------------------------------------------------------
# Requests - needs to happen 1st before populating solved model
    
    # Employee requests
    # for e, s, d, w in requests:
    #     obj_bool_vars.append(work[e, s, d])
    #     obj_bool_coeffs.append(w)
    
    # Request: (employee, shift, day, weight)
    # A negative weight indicates that the employee desire this assignment.
    # requests = [
    #     # Employee 3 does not want to work on the first Saturday (negative weight
    #     # for the Off shift).
    #     (3, 0, 5, -2),
    #     # Employee 5 wants a night shift on the second Thursday (negative weight).
    #     (5, 3, 10, -2),
    #     # Employee 2 does not want a night shift on the first Friday (positive
    #     # weight).
    #     (2, 3, 4, 4)
    # ]

# ------------------------------------------------------------------------------------------------------------

    def populate_model_with_request(self, weight, work):
        self.obj_bool_vars_min.append(work)
        self.obj_bool_coeffs_min.append(weight)
    
    def parse_requests_to_model_format(self, request):
        worker = request["workerId"]
        strategy = request["strategy"] or "AFFIRM"
        day = parse_ISO8601_date_to_datetime(request["date"]).date()
        typename = request["type"]
        if typename == 'Leave':
            request_type = typename
            slot = request['leaveId']
        elif typename == 'Duty':
            request_type = typename
            slot = request['dutyId']
        return (worker, day, slot, request_type, strategy)
    
    def parse_shift_requests_to_model_format(self, request):
        duties = []
        other_duties = []
        strategy = request["strategy"]
        worker = request["workerId"]
        day = parse_ISO8601_date_to_datetime(request["date"]).date()
        request_type = request["type"]
        _duties = utils.filter_duties_by_shift(self.df, request["shiftId"])
        _other_duties = utils.filter_duties_by_not_shift(self.df, request["shiftId"])
        
        for duty_id in _duties:
            _payload = (worker, day, duty_id, request_type, strategy)
            duties.append(_payload)
            
        for duty_id in _other_duties:
            _payload = (worker, day, duty_id, request_type, strategy)
            other_duties.append(_payload)
            
        return duties, other_duties

    def populate_requests(self):
        """populate all approved request to true, then false for all workers who did not apply for the rest days and of leave types"""
        print("populating requests")
        
        for request in self.requests:
            if request['type'] != "Shift":
                try:
                    worker, day, slot, request_type, strategy = self.parse_requests_to_model_format(request)
                    work = self.work[(worker, day, slot)]
                    self.request_list.append((worker, day, slot))
                    self.schedule_data.setdefault(day, {})
                    if strategy == "NEGATE":
                        self.model.Add(self.work[(worker, day, slot)] == 0)
                    else:
                        self.populate_model_with_request(-50, work)
                except Exception as e:
                    print(e)
                    
            else:
                duties, other_duties = self.parse_shift_requests_to_model_format(request)
                if request["strategy"] == "AFFIRM":
                    off_day_negate = []
                    for duty in other_duties:
                        try:
                            worker, day, slot, request_type, strategy = duty
                            self.model.Add(self.work[(worker, day, slot)] == 0)
                            if (worker, day) not in off_day_negate:
                                self.model.Add(self.work[(worker, day, self.off_day_id)] == 0)
                                off_day_negate.append((worker, day))
                        except Exception as e:
                            print(e)
                        
                for duty in duties:
                    try:
                        worker, day, slot, request_type, strategy = duty
                        work = self.work[(worker, day, slot)]
                        if strategy == "NEGATE":
                            self.model.Add(self.work[(worker, day, slot)] == 0)
                        else:
                            self.populate_model_with_request(-50, work)                           
                    except Exception as e:
                        print(e)
    
# ------------------------------------------------------------------------------------------------------------
#  Transitions    
# ------------------------------------------------------------------------------------------------------------
# {'sequence': [{'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 0}, {'type':'', 'id': '', 'day': 2}, {'type': 'duty', 'id': 'OFF_DAY', 'day': 2}], 'cost': 4, 'strategy': 'max'},
# {'sequence': [{'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 0}, {'type':'shift', 'id':'21c993d9-b088-45b1-b859-d53f019cc94e', 'day': 1}], 'cost': 0, 'strategy': 'never'},
# {'sequence': [{'type':'shift', 'id':'21c993d9-b088-45b1-b859-d53f019cc94e', 'day': 0}, {'type':'shift', 'id':'6e2db059-b7f1-477a-b4b7-8c1957885897', 'day': 1}], 'cost': 0, 'strategy': 'never'}

    def iterate_rules_for_each_worker(self, w, d, duties_by_shift):
        all_transition = []
        for rule_set in self.transition_rules:
            counter = 0
            single_transition = []
            slots = []
            sequence = rule_set['sequence']
            for rule in [sequence[0], sequence[-1]]:
                rule_id = rule['id']
                if rule['type'] == 'Duty':
                    slot_id = rule_id
                    slots.append([slot_id])
                    counter += rule['day']
                elif rule['type'] == 'Leave':
                    slot_id = rule_id
                    slots.append([slot_id])
                    counter += rule['day']
                    if slot_id not in self.leaves_dependent_on_shift:
                        self.leaves_dependent_on_shift.append(slot_id)
                elif rule['type'] == 'Shift':
                    slot_id = duties_by_shift[rule_id]
                    slots.append(slot_id)
                    counter += rule['day']
            
            for prev_shift, next_shift in product(slots[0], slots[-1]):
                date = d + datetime.timedelta(days=counter)
                transition = (w, d, prev_shift), (w, date, next_shift), rule_set['cost'], rule_set['strategy']
                single_transition.append(transition)
                                         
                all_transition.append(single_transition) #possible bug here?
            
        return all_transition

    def implement_sequence_constraints(self, prev_shift, next_shift, strategy, cost):

        if strategy == 'never':
            try:
                transition = [
                    self.work[prev_shift].Not(), self.work[next_shift].Not()
                ]
                self.model.AddBoolOr(transition)
            except Exception as e:
                pass

        elif strategy == 'min':
            try:
                transition = [
                    self.work[prev_shift].Not(), self.work[next_shift].Not()
                ]
                w, d, s = prev_shift
                trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
                transition.append(trans_var)
                self.model.AddBoolOr(transition)
                self.obj_bool_vars_min.append(trans_var)
                self.obj_bool_coeffs_min.append(cost)
            except Exception as e:
                pass
            
        elif strategy == 'max':
            try:
                transition = [
                    self.work[prev_shift], self.work[next_shift]
                ]
                w, d, s = prev_shift

                trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
                transition.append(trans_var)
                # self.model.AddBoolAnd(transition)
                self.model.AddImplication(self.work[prev_shift], self.work[next_shift])
                self.obj_bool_vars_min.append(trans_var)
                self.obj_bool_coeffs_min.append(-cost)
            except Exception as e:
                print(e, 'has no transition')
        
        elif strategy == 'always':
            try:
                self.model.AddImplication(self.work[prev_shift], self.work[next_shift])
            except Exception as e:
                print(e, 'has no transition')

#         elif strategy == 'max':
#             try:
#                 transition = [
#                     self.work[prev_shift], self.work[next_shift]
#                 ]
#                 transition_not = [
#                     self.work[prev_shift].Not(), self.work[next_shift].Not()
#                 ]
#                 trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
#                 self.model.AddBoolAnd(transition).OnlyEnforceIf(trans_var)
#                 self.model.AddBoolOr(transition_not).OnlyEnforceIf(trans_var.Not())
#                 # transition = [
#                 #     self.work[prev_shift], self.work[next_shift]
#                 # ]
#                 # w, d, s = prev_shift
#                 # trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
#                 # transition.append(trans_var)
#                 # self.model.AddBoolOr(transition)
#                 self.obj_bool_vars_min.append(trans_var)
#                 self.obj_bool_coeffs_min.append(-cost)
#             except Exception as e:
#                 pass
        
#         elif strategy == 'always':
#             try:
#                 # transition = [
#                 #     self.work[prev_shift].Not(), self.work[next_shift].Not()
#                 # ]
#                 # trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
#                 # transition.append(trans_var)
#                 # self.model.AddBoolOr(transition)
#                 # model.AddImplication(trans_var, self.work[prev_shift]);
#                 # model.AddImplication(trans_var, self.work[next_shift]);

                
#                 # trans_var = self.model.NewBoolVar(f'transition (w={w}, day={d})')
#                 # model.Add(transition).OnlyEnforceIf(trans_var)
#                 # model.Add(transition).OnlyEnforceIf(trans_var.Not())
#                 self.model.AddImplication(self.work[prev_shift], self.work[next_shift])
#             except Exception as e:
#                 pass

    def generate_transition_rules_model(self, duties_by_shift):
        print("starting transition rules")
        _date_list = self.date_list.copy()
        _date_list.extend(self.date_prior_list)
        for w in self.workers_list:
            for d in _date_list:
                rules = self.iterate_rules_for_each_worker(w, d, duties_by_shift)
                for rule in rules:
                    for combinations in rule:
                        prev_shift, next_shift, cost, strategy = combinations
                        self.implement_sequence_constraints(prev_shift, next_shift, strategy, cost)
                        
# ------------------------------------------------------------------------------------------------------------
# maximize excess for covers
# ------------------------------------------------------------------------------------------------------------

    def excess_covers(self):
        num_workers = len(self.workers_list)
        for d in self.date_list:
            for s in self.duty_id_for_dates[d]:
                min_, max_ = utils.get_min_max_staffs(self.df, d, s)
                min_staff, max_staff = int(min_), int(max_)
                works = [self.work[(w, d, s)] for w in self.workers_list]
                # Ignore Off shift.
                # min_demand = weekly_cover_demands[d][s - 1]
                worked = self.model.NewIntVar(min_staff, num_workers, '')
                self.model.Add(worked == sum(works))
                # over_penalty = excess_cover_penalties[s - 1]
                over_penalty = 5
                if over_penalty > 0:
                    name = f'excess_demand(shift={s}, day={d})'
                    excess = self.model.NewIntVar(0, num_workers - min_staff, name)
                    self.model.Add(excess == worked - min_staff)
                    self.obj_bool_vars_min.append(excess)
                    self.obj_bool_coeffs_min.append(over_penalty)
                    
# ------------------------------------------------------------------------------------------------------------
#  MAKE IT FLEXIBLE
# ------------------------------------------------------------------------------------------------------------               
    
    def make_it_flexible(self, num_dummy: int, role_list):
        for i in range(num_dummy):
            dummy_id = f"dummy_{i + 1}"
            self.workers_roles[dummy_id] = role_list
            self.workers_list.append(dummy_id)
        
# ------------------------------------------------------------------------------------------------------------
#  Objectives
# ------------------------------------------------------------------------------------------------------------

    def minimize(self):
        self.model.Minimize(
            sum(self.obj_bool_vars_min[i] * self.obj_bool_coeffs_min[i]
                for i in range(len(self.obj_bool_vars_min))) + 
            sum(self.obj_int_vars[i] * self.obj_int_coeffs[i]
                for i in range(len(self.obj_int_vars)))
        )

# ------------------------------------------------------------------------------------------------------------
#  Worker per shift
# ------------------------------------------------------------------------------------------------------------

    def number_workers_per_shift(self):
    #     """constraint no of worker per shift is between mix & max_staff"""
        print("constraint no of worker per shift is between mix & max_staff")
        for d in self.date_list:
            for s in self.duty_id_for_dates[d]:
                min_, max_ = utils.get_min_max_staffs(self.df, d, s)
                min_staff, max_staff = int(min_), int(max_)
                self.model.Add(sum(self.work[(w, d, s)] for w in self.workers_list) >= min_staff)
                self.model.Add(sum(self.work[(w, d, s)] for w in self.workers_list) <= max_staff)

    def maximize_workers_per_shift(self):
        """objective function to maximize no of worker per shift is between mix & max_staff"""
        print("objective function to maximize no of worker per shift is between mix & max_staff")
        # constraint to maximize no worker per shift.
        for d in self.date_list:
            for s in self.duty_id_for_dates[d]:
                self.model.Maximize(
                    sum(self.work[(w, d, s)] for w in self.workers_list)
                )

# ------------------------------------------------------------------------------------------------------------
#  Solve
# ------------------------------------------------------------------------------------------------------------                

    def solve(self):
        """solve model, returns a solution status which can be used to print solution status"""
        return self.solver.Solve(self.model)

    def check_feasibility(self):
        """returns solution status accepts a solution status which is a solver object"""
        solution_status = self.solve()
        if solution_status == cp_model.INFEASIBLE:
            status = "INFEASIBLE"
            # raise Exception(status)
        elif solution_status not in [cp_model.FEASIBLE, cp_model.OPTIMAL]:
            status = "INFEASIBLE"
            # raise Exception(status)
        elif solution_status == cp_model.OPTIMAL:
            status = "OPTIMAL"
        else:
            status = "FEASIBLE"
        
        return status
        
# ------------------------------------------------------------------------------------------------------------
#  Populate solution
# ------------------------------------------------------------------------------------------------------------   

    def populate_solved_data(self, include_leaves=True):
        """populate sovled model object, where solution status which is a solver object. will include leaves by default"""
        
        solution_status = self.solve()
        print('\nStatistics')
        print('  - conflicts: %i' % self.solver.NumConflicts())
        print('  - objective value: %i' % self.solver.ObjectiveValue())
        print('  - branches : %i' % self.solver.NumBranches())
        print('  - wall time: %f s' % self.solver.WallTime())
        if solution_status == cp_model.OPTIMAL or solution_status == cp_model.FEASIBLE:
            print("solution optimal!")
            for d in self.date_list:
                worker_assigned = []
                self.schedule_data.setdefault(d, {})
                
                if include_leaves:
                    for l in self.leaves_id_for_dates[d]:
                        worker_in_leaves_data = []
                        for w in self.workers_list:
                            if self.solver.Value(self.work[(w, d, l)]) == 1:
                                worker_in_leaves_data.append(w)
                                worker_assigned.append(w)
                            self.schedule_data[d][l] = worker_in_leaves_data
                        
                for s in self.duty_id_for_dates[d]:
                    worker_in_shift_data = []
                    for w in self.workers_list:
                        if self.solver.Value(self.work[(w, d, s)]) == 1:
                            worker_in_shift_data.append(w)
                            worker_assigned.append(w)
                    self.schedule_data[d].setdefault(s, [])
                    self.schedule_data[d][s].extend(worker_in_shift_data)
                
                # worker_not_assigned = [worker for worker in self.workers_list if worker not in worker_assigned]
                # self.schedule_data[d]['UNASSIGNED'] = worker_not_assigned
        elif solution_status == cp_model.INFEASIBLE:
            print("solution infeasible")

    def print_solver_value(self):
        for w in self.workers_list:
            for d in self.date_list:
                for s in self.duty_id_for_dates[d]:
                    print(f'{w},{d},{s}', self.solver.Value(self.work[(w, d, s)]))

# ------------------------------------------------------------------------------------------------------------
#  Transform solution
# ------------------------------------------------------------------------------------------------------------   
    def check_requested(self, df_worker, df_day, df_slot):
        _date = pd.to_datetime(df_day).date()
        return (df_worker, _date, df_slot) in self.request_list
    
    def get_request_id(self, default_id, date, workerId):
        try:
            return [request["id"] for request in self.requests if request["date"] == date and request["workerId"] == workerId][0]
        except Exception as e:
            return default_id
    
    def lambda_payload(self, include_leaves=True, include_requests=True):
        roster_list = []
        df = self.df
        for day in self.schedule_data:
            pre_roster = utils.flatten_roster_per_day(day, df)
            pre_roster['worker_id'] = pre_roster['id'].map(self.schedule_data[day])
            roster_list.append(pre_roster)

        roster = pd.concat(roster_list)
        roster = roster.explode('worker_id')
        # for worker, day, slot in self.request_list:
        #     roster_requested = roster[(roster['worker_id'] == worker) & (roster['start'] == day) & (roster['id'] == slot)]

        roster['start'] = pd.to_datetime(roster['start'])
        roster['end'] = pd.to_datetime(roster['end'])
        
        roster['requested'] = roster.apply(lambda x: self.check_requested(x['worker_id'], x['start'], x['id']), axis=1)
        
        roster['start'] = roster['start'].apply(lambda x: x.strftime('%Y-%m-%d'))
        roster['end'] = roster['end'].apply(lambda x: x.strftime('%Y-%m-%d'))
        roster["id"] = roster.apply(lambda x: self.get_request_id(x["id"], x["start"], x["worker_id"]), axis=1)
        _selected_columns = [
            'id', 
            'start', 
            'end', 
            'duty_id', 
            'duty_name',
            'role_id',
            'role_name',
            'type',
            'worker_id',
            'requested'
        ]
        
        if include_leaves:
            selected_columns = _selected_columns + ['leave_id', 'leave_name']
        else:
            selected_columns = _selected_columns
            
        if include_requests:
            _roster = roster
        else:
            _roster = roster[roster["requested"] == False]
        
        final_roster = _roster.reset_index(drop=True)[selected_columns]
        return final_roster.to_json(orient='records')
    
    def default_model(
        self,
        constraints, 
        duties_by_shift, 
        min_off_day = 0, 
        max_off_day = 1, 
        selected_roster = [],
        selected_duties_paylod = True,
        selected_leaves_payload = True
    ):
        print('using default model')
        self.create_model_duties()
        self.create_model_leaves()
        self.number_off_day_per_worker_per_roster(params=[min_off_day, max_off_day])
        self.one_worker_one_shift()

        self.build_previous_roster()
        self.use_current_selected_roster(selected_roster)

        self.number_workers_per_shift()
        
        self.match_worker_role_and_shift_hard()
        
        self.implement_slot_sequence_constraints(duties_by_shift)
        self.implement_sum_constraint()
        self.generate_transition_rules_model(duties_by_shift)

        #initialize dictionary of function from jadual lib
        constraints_func = self.get_functions_dict()

        #iterate based on functions
        for constraint in constraints:
            constraints_func[constraint["functionName"]]()
        self.populate_requests()
        self.excess_covers()
        self.minimize()
        self.use_current_selected_roster(selected_roster)
        self.solve()
        self.check_feasibility()
        self.populate_solved_data()

        return self.lambda_payload()
    
    def use_selected_roster_model(
        self, 
        constraints, 
        duties_by_shift, 
        min_off_day, 
        max_off_day,
        include_requests,
        selected_roster = [], 
        include_leaves = False, 
        include_duties= False,
        include_off_days = False, 
        
    ):
        """this model takes a dynamic parameter of leaves and off days"""
        print('using selected model')
        self.create_model_duties()
        if include_leaves:
            self.create_model_leaves()
        
        
        self.one_worker_one_shift()
        self.number_off_day_per_worker_per_roster(params=[min_off_day, max_off_day])
        self.build_previous_roster()
        self.use_current_selected_roster(selected_roster)
        self.number_workers_per_shift()
        
        self.match_worker_role_and_shift_hard()
        
        self.implement_slot_sequence_constraints(duties_by_shift)
        self.implement_sum_constraint()
        self.generate_transition_rules_model(duties_by_shift)

        #initialize dictionary of function from jadual lib
        constraints_func = self.get_functions_dict()

        #iterate based on functions
        for constraint in constraints:
            constraints_func[constraint["functionName"]]()
        
        print('requests', include_requests)
        if include_requests:
            self.populate_requests()

        self.excess_covers()
        self.minimize()
        self.use_current_selected_roster(selected_roster)
        self.solve()
        self.check_feasibility()
        self.populate_solved_data(include_leaves)

        return self.lambda_payload(include_leaves)