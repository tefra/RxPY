import logging
from collections import OrderedDict

from rx.core import AnonymousObservable, ObservableBase
from rx.internal.utils import add_ref
from rx.disposables import SingleAssignmentDisposable, RefCountDisposable, \
    CompositeDisposable
from rx.subjects import Subject

log = logging.getLogger("Rx")


def group_join(self, right, left_duration_mapper, right_duration_mapper, result_mapper) -> ObservableBase:
    """Correlates the elements of two sequences based on overlapping
    durations, and groups the results.

    Keyword arguments:
    right -- The right observable sequence to join elements for.
    left_duration_mapper -- A function to select the duration (expressed
        as an observable sequence) of each element of the left observable
        sequence, used to determine overlap.
    right_duration_mapper -- A function to select the duration (expressed
        as an observable sequence) of each element of the right observable
        sequence, used to determine overlap.
    result_mapper -- A function invoked to compute a result element for
        any element of the left sequence with overlapping elements from the
        right observable sequence. The first parameter passed to the
        function is an element of the left sequence. The second parameter
        passed to the function is an observable sequence with elements from
        the right sequence that overlap with the left sequence's element.

    Returns an observable sequence that contains result elements computed
    from source elements that have an overlapping duration.
    """

    left = self

    def subscribe(observer, scheduler=None):
        nothing = lambda _: None
        group = CompositeDisposable()
        r = RefCountDisposable(group)
        left_map = OrderedDict()
        right_map = OrderedDict()
        left_id = [0]
        right_id = [0]

        def on_next_left(value):
            s = Subject()

            with self.lock:
                _id = left_id[0]
                left_id[0] += 1
                left_map[_id] = s

            try:
                result = result_mapper(value, add_ref(s, r))
            except Exception as e:
                log.error("*** Exception: %s" % e)
                for left_value in left_map.values():
                    left_value.on_error(e)

                observer.on_error(e)
                return

            observer.on_next(result)

            for right_value in right_map.values():
                s.on_next(right_value)

            md = SingleAssignmentDisposable()
            group.add(md)

            def expire():
                if _id in left_map:
                    del left_map[_id]
                    s.on_completed()

                group.remove(md)

            try:
                duration = left_duration_mapper(value)
            except Exception as e:
                for left_value in left_map.values():
                    left_value.on_error(e)

                observer.on_error(e)
                return

            def on_error(error):
                for left_value in left_map.values():
                    left_value.on_error(error)

                observer.on_error(error)

            md.disposable = duration.take(1).subscribe_(nothing, on_error, expire, scheduler)

        def on_error_left(error):
            for left_value in left_map.values():
                left_value.on_error(error)

            observer.on_error(error)

        group.add(left.subscribe_(on_next_left, on_error_left, observer.on_completed, scheduler))

        def send_right(value):
            with self.lock:
                _id = right_id[0]
                right_id[0] += 1
                right_map[_id] = value

            md = SingleAssignmentDisposable()
            group.add(md)

            def expire():
                del right_map[_id]
                group.remove(md)

            try:
                duration = right_duration_mapper(value)
            except Exception as e:
                for left_value in left_map.values():
                    left_value.on_error(e)

                observer.on_error(e)
                return

            def on_error(error):
                with self.lock:
                    for left_value in left_map.values():
                        left_value.on_error(error)

                    observer.on_error(error)

            md.disposable = duration.take(1).subscribe_(nothing, on_error, expire, scheduler)

            with self.lock:
                for left_value in left_map.values():
                    left_value.on_next(value)

        def on_error_right(error):
            for left_value in left_map.values():
                left_value.on_error(error)

            observer.on_error(error)

        group.add(right.subscribe_(send_right, on_error_right, scheduler=scheduler))
        return r
    return AnonymousObservable(subscribe)
