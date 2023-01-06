import datetime

def set_time(hour):
    _date = datetime.datetime(year=2023, month=1, day=1, hour=hour)
    return _date.time()

def is_weekend(date):
    return date.weekday() in [5, 6]


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