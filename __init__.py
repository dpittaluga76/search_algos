import time
import bisect
from multiprocessing import Process, Queue
from functools import wraps
import cProfile
__author__ = "Daniel Pittaluga"


def profile_this(func):
    """Benchmark and build a response."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        cp = cProfile.Profile()
        cp.enable()

        result = func(*args, **kwargs)

        cp.disable()
        cp.print_stats()

        return result
    return wrapper


def show_runtime_and_result(func):
    """Benchmark and build a response."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        print("-"*20)
        print(f'Started {func.__name__}')
        start = time.perf_counter()
        result = func(*args, **kwargs)

        end = time.perf_counter()
        time_taken = end - start

        if result is not None:
            print('{} found at positions: {}, took %f'.format(args[1], result) % time_taken)
    return wrapper


@show_runtime_and_result
def linear_search(input_list, lookup_value, queue=None):
    """Linear search algorithm
    :param input_list: some sorted collection with comparable items
    :param lookup_value: item value to search
    :param queue: only used for multiprocessing to add item to queue
    :return: index of found item or None if not found
    Examples:
    >>> linear_search([0, 15, 17, 20, 25], 20)
    3
    >>> linear_search([0, 11, 22, 30, 40], 6)
    """
    for index, item in enumerate(input_list):
        if item == lookup_value:
            if queue is not None:
                queue.put(index)
            return index
    queue.put(None)
    return None


@show_runtime_and_result
def binary_search(input_list, lookup_value, queue=None):
    """Binary search algorithm
    Note that input list must be in ascending order, otherwise won't work
    :param input_list: should be previously sorted in ascending order
    :param lookup_value: item value to search
    :param queue: only used for multiprocessing to add item to queue
    :return: index of found item or None if not found
    Examples:
    >>> binary_search([0, 3, 5, 33, 44], 0)
    0
    >>> binary_search([0, 1, 2, 3, 4], 6)
    """
    first = 0
    last = len(input_list) - 1

    while first <= last:
        middle_item = first + (last - first) // 2
        current_item = input_list[middle_item]
        if current_item == lookup_value:
            if queue is not None:
                queue.put(middle_item)
            return middle_item
        else:
            if lookup_value < current_item:
                last = middle_item - 1
            else:
                first = middle_item + 1
    queue.put(None)
    return None


@show_runtime_and_result
def binary_search_std_lib(input_list, lookup_value):
    """Binary search algorithm using bisect
    :param input_list: some ascending sorted list
    :param lookup_value: item value to search
    :return: index of found item or None if item is not found
    Examples:
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 0)
    0
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 15)
    4
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 5)
    1
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 6)
    """
    index = bisect.bisect_left(input_list, lookup_value)
    if index != len(input_list) and input_list[index] == lookup_value:
        return index
    return None


@show_runtime_and_result
def binary_search_by_recursion(input_list, lookup_value, left, right):
    """ binary search algorithm by recursion
    First recursion should be started with left=0 and right=(len(sorted_collection)-1)
    :param input_list: some ascending sorted collection with comparable items
    :param lookup_value: item value to search
    :param left: left item
    :param right: right item
    :return: index of found item or None if item is not found
    Examples:
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 0)
    0
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 6)
    """
    if right < left:
        return None

    midpoint = left + (right - left) // 2

    if input_list[midpoint] == lookup_value:
        return midpoint
    elif input_list[midpoint] > lookup_value:
        return binary_search_by_recursion(input_list, lookup_value, left, midpoint-1)
    else:
        return binary_search_by_recursion(input_list, lookup_value, midpoint+1, right)


@show_runtime_and_result
def interpolation_search(input_list, lookup_value):
    """Interpolation algorithm
    :param input_list: some ascending sorted collection with comparable items
    :param lookup_value: item value to search
    :return: index of found item or None if item is not found
    Examples:
    >>> interpolation_search([0, 5, 7, 10, 15], 0)
    0
    >>> interpolation_search([0, 5, 7, 10, 15], 6)
    """
    low = 0
    high = (len(input_list) - 1)
    while low <= high and input_list[low] <= lookup_value <= input_list[high]:
        index = low + int(((float(high - low) / (input_list[high] - input_list[low])) * (lookup_value - input_list[low])))
        if input_list[index] == lookup_value:
            return index
        if input_list[index] < lookup_value:
            low = index + 1
        else:
            high = index - 1
    return -1


@show_runtime_and_result
def find_by_sets(input_list, lookup_value):
    """Find using python sets
    :param input_list: some ascending sorted collection with comparable items
    :param lookup_value: item value to search
    :return: doesn't return index but tells if value is present
    Examples:
    >>> find_by_sets([0, 5, 7, 10, 15], 5)
    5
    >>> find_by_sets([0, 5, 7, 10, 15], 6)
    """
    #  set Search
    a = set(input_list)
    b = {lookup_value}
    result = a.intersection(b)
    return result


def multiproc_gensample(func, lst_size, cpu_cnt):
    print('Testing multiprocessing w/ {0} cores'.format(cpu_cnt))
    queue1 = Queue()
    procs = []

    step_every = (lst_size//cpu_cnt)
    skip_remainder = (lst_size % cpu_cnt)
    print ('step every', step_every)
    for i in range(0,lst_size-skip_remainder, step_every):

        if i == int(lst_size*cpu_cnt):
            add_remainder = lst_size % cpu_cnt
            print(lst_size % cpu_cnt)
        else:
            add_remainder = 0
        proc = Process(target=func, args=(queue1))
        procs.append(proc)

    for proc in procs:
        proc.start()

    st_output = [queue1.get() for p in procs]
    print(st_output)
    # complete the processes

    for proc in procs:
        proc.join()

def multiproc_test(func, lst_size, seq, tgt, cpu_cnt):
    print('Testing multiprocessing w/ {0} cores'.format(cpu_cnt))
    queue1 = Queue()
    procs = []

    step_every = (lst_size//cpu_cnt)
    skip_remainder = (lst_size % cpu_cnt)
    print ('step every', step_every)
    for i in range(0,lst_size-skip_remainder, step_every):

        if i == int(lst_size*cpu_cnt):
            add_remainder = lst_size % cpu_cnt
            print(lst_size % cpu_cnt)
        else:
            add_remainder = 0
        proc = Process(target=func, args=(seq[i:i+step_every+add_remainder], tgt, queue1))
        procs.append(proc)

    for proc in procs:
        proc.start()

    st_output = [queue1.get() for p in procs]
    print(st_output)
    # complete the processes

    for proc in procs:
        proc.join()
