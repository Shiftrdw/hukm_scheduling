import utils

senior, junior = "Senior", "Junior"
am, am_s, pm, n, no, do, al = "Morning", "Morning stayback", "Evening", "Night", "Night off", "Day off", "Annual leave"

nurses = [
    "Azatuliana",
    "Fatehah",
    "Fatimah",
    "Fazilawati",
    "Mimi",
    "Nur aimi",
    "Sariah",
    "Siti sakinah",
    "Tina",
    "Wahidah",
         ]

roles = {
    "Azatuliana": senior,
    "Fatehah": junior,
    "Fatimah": senior,
    "Fazilawati": senior,
    "Mimi": senior,
    "Nur aimi": junior,
    "Sariah": senior,
    "Siti sakinah": senior,
    "Tina": senior,
    "Wahidah": junior,
}

shift = {
    am: {
        "start": utils.set_time(7),
        "end": utils.set_time(14)
    },
    am_s: {
        "start": utils.set_time(7),
        "end": utils.set_time(17)
    },
    pm: {
        "start": utils.set_time(14),
        "end": utils.set_time(21)
    },
    n: {
        "start": utils.set_time(21),
        "end": utils.set_time(7)
    }
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

weekly_cover_demands = [
    (3, 3, 1),  # Monday
    (3, 3, 1),  # Tuesday
    (3, 3, 1),  # Wednesday
    (3, 3, 1),  # Thursday
    (3, 3, 1),  # Friday
    (3, 3, 1),  # Saturday
    (3, 3, 1),  # Sunday
]

shift_min_covers = {
    am: 3,
    am: (1,2)
    pm: 3,
    n: 1
}

night_sequence = ({
    0: n,
    1: n,
    2: no
}, "always", 0)

night_off_sequence = ({
    0: no,
    1: am
}, "never", 0)

night_off_max_pm = ({
    0: no,
    1: pm
}, "max", 5)

night_off_max_do = ({
    0: no,
    1: do
}, "max", 10)

#excess cover for am, pm, n
excess_cover_penalties = (2, 2, 5)