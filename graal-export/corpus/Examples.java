/**
 * Optimizations Graal misses and the token form should make.
 */
public class Examples {

    static class Counter { int value; int other; }
    static class Logger { int count; }
    static class Link { Link next; }

    // This is recursive on purpose, so inlining can't remove the call.
    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    // Recursive too, and it writes Counter.value: the callee of the controls.
    static void countInto(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countInto(counter, link.next);
        }
    }

    // The same for a Logger: it writes only Logger.count.
    static void countInto(Logger logger, Link link) {
        if (link != null) {
            logger.count++;
            countInto(logger, link.next);
        }
    }

    interface Shape { int area(); }
    static final class Square implements Shape { int side; public int area() { return side * side; } }
    static final class Rect implements Shape { int width, height; public int area() { return width * height; } }

    
    static void deadStoreOtherField(Counter counter) {
        counter.value = 1; // dead store
        counter.other = 7;
        counter.value = 2;
    }

    static void deadStoreMaybeAliasControl(Counter counter, Counter alias) {
        counter.value = 1;
        counter.other = alias.value;
        counter.value = 2;
    }

    static void deadStoreOtherObject(Counter counter, Logger logger) {
        int seen = logger.count;
        counter.value = 1; // dead store 
        logger.count = seen + 1;
        counter.value = 2;
    }

    static void deadStoreBothArms(Counter counter, boolean flag) {
        counter.value = 0; // dead store
        if (flag) {
            counter.value = 1;
        } else {
            counter.value = 2;
        }
    }

    static void deadStoreOneArm(Counter counter, boolean flag) {
        counter.value = 0; // not necessarily a dead store
        if (flag) {
            counter.value = 1;
        }
    }

    // Control: alias may be another object, so its store doesn't overwrite the
    // first. Checking alias for null first keeps both stores in one block.
    static void deadStoreMaybeAliasStoreControl(Counter counter, Counter alias) {
        alias.other = 0;
        counter.value = 1;
        alias.value = 2;
    }

    // On the flag path the load reads the 1, which the last store overwrites:
    // Graal duplicates the merge, forwards the load on that path and drops the
    // first store. Without forwarding across a merge, the load still reads it.
    static int deadStoreReadAfterMerge(Counter counter, boolean flag) {
        if (flag) {
            counter.value = 1;
        }
        int seen = counter.value;
        counter.value = 2;
        return seen;
    }

    // The load in the arm reads the 1 stored before the branch: it takes the 1
    // instead, and the store is dead. The call keeps Graal from forwarding the
    // load before the analysis.
    static int deadStoreReadInArm(Counter counter, Link list, boolean flag) {
        counter.value = 1;
        int n = length(list);
        if (flag) {
            n += counter.value;
        }
        counter.value = 2;
        return n;
    }

    static int deadStoreReadInLoop(Counter counter, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += counter.value + length(list);
        }
        counter.value = 2;
        return sum;
    }

    // Each iteration reads what the iteration before stored, the first the 1:
    // the loop carries the value as a phi, the load goes, and so do the
    // stores, which only the next iteration read. The call before the load
    // keeps Graal from forwarding it before the analysis.
    static int forwardAcrossIterations(Counter counter, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
            counter.value = i;
        }
        counter.value = 2;
        return sum;
    }

    // As forwardAcrossIterations with nothing stored before the loop: the
    // first iteration is peeled, and the rest take what the iteration before
    // stored as a phi. Every store in the loop goes, since the next
    // iteration's store or the one after the loop overwrites it.
    static int forwardAcrossIterationsPeeled(Counter counter, Link list, int times) {
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
            counter.value = i;
        }
        counter.value = 2;
        return sum;
    }

    // Control: each iteration stores through alias, which may be another
    // object, so the next iteration's load can't take that value, and the
    // first iteration's load, which reads the 1, keeps that store.
    static int forwardAcrossIterationsAliasControl(Counter counter, Counter alias, Link list, int times) {
        counter.value = 1;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += length(list) + counter.value;
            alias.value = i;
        }
        counter.value = 2;
        return sum;
    }

    // Control: before the first loop the store goes through alias, which may
    // be another object, and with one heap token a store to another field
    // follows it; in the second loop c is alias from the second iteration on.
    // Neither loop can take the value stored before it. Both loads still leave
    // their loops: the first loop only reads, and the second loop's object
    // settles after its first iteration.
    static int forwardIntoLoopAliasControl(Counter counter, Counter alias, int times) {
        alias.value = 1;
        counter.other = 2;
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += counter.value;
        }
        counter.value = 3;
        Counter c = counter;
        for (int i = 0; i < times; i++) {
            sum += c.value;
            c = alias;
        }
        return sum;
    }

    static int forwardAcrossCall(Counter counter, Link list) {
        counter.value = 5;
        int n = length(list); // length(list) doesn't touch Counter.value, yet
        return counter.value + n;  // Graal produces redundant load here
    }

    // Control: alias may be another object, so the load in the arm can't take
    // the value stored through counter; with one heap token, the store to
    // alias.other comes between them.
    static int forwardIntoArmAliasControl(Counter counter, Counter alias, boolean flag) {
        counter.value = 1;
        alias.other = 2;
        int n = 0;
        if (flag) {
            n = alias.value;
        }
        return n;
    }

    // Control: alias may be another object, so its load can't take the value
    // stored through counter. Checking alias for null first keeps them in one block.
    static int forwardMaybeAliasControl(Counter counter, Counter alias) {
        alias.other = 0;
        counter.value = 1;
        return alias.value;
    }

    // Control: countInto writes Counter.value.
    static int forwardAcrossCallControl(Counter counter, Link list) {
        counter.value = 5;
        countInto(counter, list); // countInto(counter, list) writes into counter.value
        return counter.value; // so this is not a redundant load
    }

    static int forwardAcrossWritingCall(Counter counter, Logger logger, Link list) {
        counter.value = 5;
        countInto(logger, list); // countInto(logger, list) doesn't write into counter.value
        return counter.value; // therefore this is a redundant load
    }

    // Both arms store, and the call in one leaves Counter.value alone: after
    // the merge the load takes whichever value its arm stored.
    static int forwardAcrossMerge(Counter counter, Link list, boolean flag) {
        int n = 0;
        if (flag) {
            counter.value = 1;
            n = length(list);
        } else {
            counter.value = 2;
        }
        return counter.value + n;
    }

    // Control: the second arm stores through alias, which may be another
    // object, and then to another field, so only the first arm's value
    // reaches the load.
    static int forwardAcrossMergeAliasControl(Counter counter, Counter alias, Link list, boolean flag) {
        alias.other = 0;
        counter.other = 0;
        int n = 0;
        if (flag) {
            counter.value = 1;
            n = length(list);
        } else {
            alias.value = 2;
            counter.other = 3;
        }
        return counter.value + n;
    }

    static int repeatedLoadAcrossCall(Counter counter, Link list) {
        // Yet another example of the same phenomenon (just to make sure)
        int before = counter.value;
        int n = length(list);
        return before + counter.value + n;
    }

    static int repeatedLoadAcrossCallControl(Counter counter, Link list) {
        int before = counter.value;
        countInto(counter, list); // Count write may write into counter.value
        return before + counter.value; // therefore we can't remove counter.value load
    }

    // counter.value doesn't change in the loop, so its load could leave it.
    // Also needs a read model that lets a load leave a loop.
    static int hoistLoadOutOfLoop(Counter counter, Link list, int times) {
        int sum = 0;
        for (int i = 0; i < times; i++) {
            sum += counter.value + length(list);
        }
        return sum;
    }

    // Control: each iteration reads another link, so the object never settles.
    static int hoistLoadOutOfLoopListControl(Link list) {
        int n = 0;
        for (Link l = list; l != null; l = l.next) {
            n++;
        }
        return n;
    }

    // countInto changes counter.value in every iteration.
    static int hoistLoadOutOfLoopControl(Counter counter, Link list, int times) {
        int sum = 0;
        for (int i = 0; i < times; i++) {
            countInto(counter, list);
            sum += counter.value;
        }
        return sum;
    }

    // forwardAcrossCall through a call with two possible targets. graal2ct
    // refuses it until it can dispatch on the receiver's class.
    static int forwardAcrossVirtualCall(Counter counter, Shape shape) {
        counter.value = 5;
        int area = shape.area();
        return counter.value + area;
    }

    static void unusedReadOnlyCall(Link list) {
        length(list); // length's result is unused, and it only reads: the call can go.
        // Removing this call also removes the potential StackOverFlowError it might throw,
        // Which leads to simplifying the control flow (e.g. no exceptional edges)
    }

    static void unusedWritingCall(Counter counter, Link list) {
        countInto(counter, list); // this call actually writes to a field, so we can't remove it
    }

    static int repeatedReadOnlyCall(Link list) {
        // The second call repeats the first: nothing between writes Link.next.
        return length(list) + length(list);
    }

    static int repeatedReadOnlyCallControl(Link list) {
        int first = length(list);
        if (list != null) {
            list.next = null;
        }
        // The list may change between the calls, therefore we must call length(list) again.
        return first + length(list);
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        Logger logger = new Logger();
        Link list = new Link();
        list.next = new Link();
        boolean flag = args.length > 0;
        // Not a constant: Native Image's analysis would pass it into the loops,
        // which would then unroll fully and leave no loop to look at.
        int times = args.length + 3;
        Shape shape = flag ? new Square() : new Rect();

        deadStoreOtherField(counter);
        // Each alias control also gets one counter twice: with allocation sites,
        // the analysis would otherwise tell its two references apart.
        deadStoreMaybeAliasControl(counter, new Counter());
        deadStoreMaybeAliasControl(counter, counter);
        deadStoreOtherObject(counter, logger);
        deadStoreBothArms(counter, flag);
        deadStoreOneArm(counter, flag);
        deadStoreMaybeAliasStoreControl(counter, new Counter());
        deadStoreMaybeAliasStoreControl(counter, counter);
        int sum = deadStoreReadAfterMerge(counter, flag);
        sum += deadStoreReadInArm(counter, list, flag);
        sum += deadStoreReadInLoop(counter, list, times);
        sum += forwardAcrossIterations(counter, list, times);
        sum += forwardAcrossIterationsPeeled(counter, list, times);
        sum += forwardAcrossIterationsAliasControl(counter, new Counter(), list, times);
        sum += forwardAcrossIterationsAliasControl(counter, counter, list, times);
        sum += forwardIntoLoopAliasControl(counter, new Counter(), times);
        sum += forwardIntoLoopAliasControl(counter, counter, times);
        sum += forwardIntoArmAliasControl(counter, new Counter(), flag);
        sum += forwardIntoArmAliasControl(counter, counter, flag);
        sum += forwardMaybeAliasControl(counter, new Counter());
        sum += forwardMaybeAliasControl(counter, counter);
        sum += forwardAcrossCall(counter, list);
        sum += forwardAcrossCallControl(counter, list);
        sum += forwardAcrossWritingCall(counter, logger, list);
        sum += forwardAcrossMerge(counter, list, flag);
        sum += forwardAcrossMergeAliasControl(counter, new Counter(), list, flag);
        sum += forwardAcrossMergeAliasControl(counter, counter, list, flag);
        sum += repeatedLoadAcrossCall(counter, list);
        sum += repeatedLoadAcrossCallControl(counter, list);
        sum += hoistLoadOutOfLoop(counter, list, times);
        sum += hoistLoadOutOfLoopControl(counter, list, times);
        sum += hoistLoadOutOfLoopListControl(list);
        sum += forwardAcrossVirtualCall(counter, shape);
        unusedReadOnlyCall(list);
        unusedWritingCall(counter, list);
        sum += repeatedReadOnlyCall(list);
        sum += repeatedReadOnlyCallControl(list);

        System.out.println(sum + counter.value + counter.other + logger.count);
    }
}
