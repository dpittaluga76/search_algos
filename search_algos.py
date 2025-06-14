import random
from multiprocessing import cpu_count

from lib import linear_search, \
    binary_search, \
    binary_search_std_lib, \
    interpolation_search, \
    find_by_sets, \
    binary_search_by_recursion, \
    multiproc_test

__author__ = "Daniel Pittaluga"


if __name__ == '__main__':

    user_input = input('Please enter number of items to randomly generate:\n').strip()
    list_size = int(user_input)

    #  sequence = list(set(sequence))
    sequence = random.sample(range(1, list_size+1), list_size)
    sequence.sort()

    target = sequence[random.randint(0, list_size - 1)]
    print(f'search value is {target}')

    #  linear_search(sequence, target)
    #  binary_search(sequence, target)
    #  binary_search_std_lib(sequence,target)
    #  InterpolationSearch(sequence, target)
    #  FindBySets(sequence, target)

    L = [linear_search, binary_search, binary_search_std_lib, interpolation_search, find_by_sets]
    #  [f(sequence,target) for f in L]
    for f in L:
        print (f.__name__)
        f(sequence, target)

    #  Binary III
    binary_search_by_recursion(sequence, target, 0, len(sequence))

    #  Multiprocessing
    core_count = cpu_count()
    multiproc_test(binary_search, list_size, sequence, target, core_count)
