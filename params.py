import utils

senior, junior = "Senior", "Junior"
am, ams, pm, n, no, do, al, dop = "AM", "AMS", "PM", "N", "NO", "DO", "AL", "DOP"

nurses = [f'J{i+1}' for i in range(10)]

# nurses = [
#     "Azatuliana",
#     "Fatehah",
#     "Fatimah",
#     "Fazilawati",
#     "Mimi",
#     "Nuraimi",
#     "Sariah",
#     "Sitisakinah",
#     "Tina",
#     "Wahidah",
#          ]

roles = {
    "J1": senior,
    "J2": senior,
    "J3": senior,
    "J4": senior,
    "J5": senior,
    "J6": senior,
    "J7": senior,
    "J8": senior,
    "J9": senior,
    "J10": junior,
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
    dop: {
        "start": utils.set_time(23),
        "end": utils.set_time(0)
    },
}


shift_min_covers = {
    am: 2,
    ams: (1,2),
    pm: 2,
    n: 1
}

shift_transition = [
    ({
        0: n,
        1: no
    }, "always", 0),
    ##################
    ({
        0: no,
        1: pm
    }, "max", 80),
    ({
        0: no,
        1: do
    }, "max", 100),
    ({
        0: al,
        1: do
    }, "max", 100),
    ({
        0: do,
        1: al
    }, "max", 100),
    ({
        0: no,
        1: am
    }, "min", 40),
    ({
        0: no,
        1: ams
    }, "min", 40),
    ##################
    ({
        0: no,
        1: n
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
    ({
        0: dop,
        1: no
    }, "never", 0),
    ({
        0: ams,
        1: no
    }, "never", 0),
    ({
        0: al,
        1: no
    }, "never", 0),
]

sum_constraints =[
    # slot, slot_type, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost
    (n, "weekly", 0, 0, 10, 1, 2, 10),
    (ams, "weekly", 0, 0, 10, 1, 2, 10)
]

#excess cover for am, pm, n
excess_cover_penalties = (2, 2, 5)