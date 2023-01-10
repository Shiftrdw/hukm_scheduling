import utils

senior, junior = "Senior", "Junior"
am, ams, pm, n, no, do, al = "AM", "AMS", "PM", "N", "NO", "DO", "AL"

nurses = [
    "Azatuliana",
    "Fatehah",
    "Fatimah",
    "Fazilawati",
    "Mimi",
    "Nuraimi",
    "Sariah",
    "Sitisakinah",
    "Tina",
    "Wahidah",
         ]

roles = {
    "Azatuliana": senior,
    "Fatehah": junior,
    "Fatimah": senior,
    "Fazilawati": senior,
    "Mimi": senior,
    "Nuraimi": junior,
    "Sariah": senior,
    "Sitisakinah": senior,
    "Tina": senior,
    "Wahidah": junior,
}

shift_timings = {
    am: {
        "start": utils.set_time(7),
        "end": utils.set_time(14)
    },
    ams: {
        "start": utils.set_time(7),
        "end": utils.set_time(17)
    },
    pm: {
        "start": utils.set_time(14),
        "end": utils.set_time(21)
    },
    n: {
        "start": utils.set_time(21),
        "end": utils.set_time(0)
    },
    no: {
        "start": utils.set_time(0),
        "end": utils.set_time(7)
    },
    al: {
        "start": utils.set_time(23),
        "end": utils.set_time(0)
    },
    do: {
        "start": utils.set_time(23),
        "end": utils.set_time(0)
    },
}

# Weekly sum constraints on shifts days:
    #     (shift, hard_min, soft_min, min_penalty,
    #             soft_max, hard_max, max_penalty)
weekly_sum_constraints = [
    # Constraints on rests per week.
    (n, 1, 2, 7, 2, 3, 4),
    # At least 1 night shift per week (penalized). At most 4 (hard).
    (3, 0, 1, 3, 4, 4, 0),
]

shift_constraints = [
    # One or two consecutive days of rest, this is a hard constraint.
    (0, 1, 1, 0, 2, 2, 0),
    # between 2 and 3 consecutive days of night shifts, 1 and 4 are
    # possible but penalized.
    (3, 1, 2, 20, 3, 4, 5),
]

shift_min_covers = {
    am: 2,
    ams: (1,2),
    pm: 2,
    n: 1
}

shift_transition = [
    # ({
    #     0: n,
    #     1: n,
    #     2: no
    # }, "always", 0),
    # ({
    #     0: n,
    #     1: n
    # }, "max", 20),
    ({
        0: n,
        1: no
    }, "max", 20),
    ({
        0: no,
        1: n
    }, "never", 0),
    ({
        0: n,
        3: n
    }, "never", 0),
    ({
        0: no,
        1: pm
    }, "max", 5),
    ({
        0: no,
        1: do
    }, "max", 10),
    ({
        0: no,
        1: n
    }, "never", 0),
    ({
        0: n,
        3: no
    }, "never", 0),
    ({
        0: no,
        1: no
    }, "never", 0),
    ({
        0: pm,
        1: no
    }, "never", 0),
    ({
        0: am,
        1: no
    }, "never", 0),
    ({
        0: do,
        1: no
    }, "never", 0),
    # ({
    #     0: ams,
    #     1: no
    # }, "never", 0),
]

sum_constraints =[
    # slot, slot_type, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost
    (n, "weekly", 0, 0, 10, 1, 2, 10),
    (ams, "weekly", 0, 0, 10, 1, 2, 10)
]

#excess cover for am, pm, n
excess_cover_penalties = (2, 2, 5)