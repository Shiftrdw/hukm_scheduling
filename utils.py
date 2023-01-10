import datetime
import pandas as pd

def set_time(hour):
    _date = datetime.datetime(year=2023, month=1, day=1, hour=hour)
    return _date.time()

def format_timedelta(td):
    return f'{td.days} days, {td.seconds//3600} hours, {(td.seconds//60)%60} mins'

def is_weekend(date):
    return date.weekday() in [5, 6]

def is_sunday(date):
    return date.weekday() in [6]

def is_saturday(date):
    return date.weekday() in [5]

def is_weekday(date):
    return date.weekday() in [0,1,2,3,4]

def date_range(start=(2023,1,1), end=(2023,1,1)):
    y1,m1,d1 = start
    y2,m2,d2 = end
    start_date = datetime.datetime(year=y1, month=m1, day=d1)
    end_date = datetime.datetime(year=y2, month=m2, day=d2)
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += datetime.timedelta(days=1)
    return dates

def add_days(date, days):
    return date + datetime.timedelta(days=days)

def chunk(list_a, chunk_size):
    for i in range(0, len(list_a), chunk_size):
        yield list_a[i:i + chunk_size]
        
def negated_bounded_span(works, start, length):
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

def add_soft_sequence_constraint(model, works, desired_length):

    # Forbid sequences that are too short.
    for length in range(1, desired_length):
        for start in range(len(works) - length + 1):
            print(negated_bounded_span(works, start, length))
            model.AddBoolOr(negated_bounded_span(works, start, length))

    # Just forbid any sequence of true variables with length hard_max + 1
    # for start in range(len(works) - hard_max):
    #     model.AddBoolOr(
    #         [works[i].Not() for i in range(start, start + hard_max + 1)]
    #     )

# def add_soft_sequence_constraint(model, works, hard_min, soft_min, min_cost,
#                                     soft_max, hard_max, max_cost, prefix):
#     cost_literals = []
#     cost_coefficients = []

#     # Forbid sequences that are too short.
#     for length in range(1, hard_min):
#         for start in range(len(works) - length + 1):
#             model.AddBoolOr(negated_bounded_span(works, start, length))

#     # Penalize sequences that are below the soft limit.
#     if min_cost > 0:
#         for length in range(hard_min, soft_min):
#             for start in range(len(works) - length + 1):
#                 span = negated_bounded_span(works, start, length)
#                 name = ': under_span(start=%i, length=%i)' % (start, length)
#                 lit = model.NewBoolVar(prefix + name)
#                 span.append(lit)
#                 model.AddBoolOr(span)
#                 cost_literals.append(lit)
#                 # We filter exactly the sequence with a short length.
#                 # The penalty is proportional to the delta with soft_min.
#                 cost_coefficients.append(min_cost * (soft_min - length))

#     # Penalize sequences that are above the soft limit.
#     if max_cost > 0:
#         for length in range(soft_max + 1, hard_max + 1):
#             for start in range(len(works) - length + 1):
#                 span = negated_bounded_span(works, start, length)
#                 name = ': over_span(start=%i, length=%i)' % (start, length)
#                 lit = model.NewBoolVar(prefix + name)
#                 span.append(lit)
#                 model.AddBoolOr(span)
#                 cost_literals.append(lit)
#                 # Cost paid is max_cost * excess length.
#                 cost_coefficients.append(max_cost * (length - soft_max))

#     # Just forbid any sequence of true variables with length hard_max + 1
#     for start in range(len(works) - hard_max):
#         model.AddBoolOr(
#             [works[i].Not() for i in range(start, start + hard_max + 1)])
#     return cost_literals, cost_coefficients


def add_soft_sum_constraint(model, works, hard_min, soft_min, min_cost,
                            soft_max, hard_max, max_cost, prefix):
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

def create_tuple(row):
    return (row.name, row.index, row.data)


def get_data_to_tuple(path):
    df = pd.read_excel(path, index_col=0)
    columns = df.columns
    tup = []
    for i, row in enumerate(df.itertuples()):
        for n, item in enumerate(row):
            if n == 0:
                col = item
            else:
                tup.append((col, item, columns[n-1].to_pydatetime()))
    return tup