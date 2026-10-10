public class Aliasing {

    static class Counter { int value; int other; }
    static class Link { Link next; }

    static int result;

    // Recursive on purpose, so inlining can't remove the call.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    // Writes Counter.value, but only of the counters passed to it, never a
    // method's own counter.
    static void countInto(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countInto(counter, link.next);
        }
    }

    // The same for the control, which also passes it its counter.
    static void countIntoAlias(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countIntoAlias(counter, link.next);
        }
    }

    // The store goes to another object, so the load takes the 1.
    static int forwardPastOtherObject(Counter counter, Counter other) {
        counter.value = 1;
        other.value = 2;
        return counter.value;
    }

    // Control: alias may be counter.
    static int forwardPastAliasControl(Counter counter, Counter alias) {
        counter.value = 1;
        alias.value = 2;
        return counter.value;
    }

    // The load reads another object, so the first store is dead. Reading
    // other.other first checks other for null, so nothing between the two
    // stores can throw: legal in Java, not only under the trap model.
    static int deadStorePastOtherObject(Counter counter, Counter other) {
        int seen = other.other;
        counter.value = 1;
        seen += other.value;
        counter.value = 2;
        return seen;
    }

    // Control: alias.value may read the 1.
    static int deadStorePastAliasControl(Counter counter, Counter alias) {
        int seen = alias.other;
        counter.value = 1;
        seen += alias.value;
        counter.value = 2;
        return seen;
    }

    // Each iteration stores to another object, so the load takes the 1 stored
    // before the loop. The call keeps Graal from forwarding the load before
    // the analysis.
    static int forwardIntoLoopPastOtherObject(Counter counter, Counter other, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
            other.value = i;
        }
        return sum;
    }

    // Control: alias may be counter, so an iteration may read what the one
    // before stored.
    static int forwardIntoLoopPastAliasControl(Counter counter, Counter alias, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
            alias.value = i;
        }
        return sum;
    }

    // countInto writes Counter.value, but never counter's: the call doesn't
    // take counter's token, and the load takes the 5.
    static int forwardAcrossCallOnOtherObject(Counter counter, Counter other, Link list) {
        counter.value = 5;
        countInto(other, list);
        return counter.value;
    }

    // Control: countIntoAlias may write counter.value.
    static int forwardAcrossCallOnAliasControl(Counter counter, Counter alias, Link list) {
        counter.value = 5;
        countIntoAlias(alias, list);
        return counter.value;
    }

    public static void main(String[] args) {
        Link list = new Link();
        list.next = new Link();
        int times = args.length + 3;
        Counter shared = new Counter();

        int sum = forwardPastOtherObject(new Counter(), new Counter());
        sum += forwardPastAliasControl(new Counter(), new Counter());
        sum += forwardPastAliasControl(shared, shared);
        sum += deadStorePastOtherObject(new Counter(), new Counter());
        sum += deadStorePastAliasControl(new Counter(), new Counter());
        sum += deadStorePastAliasControl(shared, shared);
        sum += forwardIntoLoopPastOtherObject(new Counter(), new Counter(), list, times);
        sum += forwardIntoLoopPastAliasControl(new Counter(), new Counter(), list, times);
        sum += forwardIntoLoopPastAliasControl(shared, shared, list, times);
        sum += forwardAcrossCallOnOtherObject(new Counter(), new Counter(), list);
        sum += forwardAcrossCallOnAliasControl(new Counter(), new Counter(), list);
        sum += forwardAcrossCallOnAliasControl(shared, shared, list);
        result = sum;
    }
}
