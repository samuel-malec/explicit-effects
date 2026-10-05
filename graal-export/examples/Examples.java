/**
 * Optimizations Graal misses and the token form should make.
 *
 * Each example is measured with graal-probe: Graal leaves the store, load or
 * call in place, with inlining and without. Each has a control, where the same
 * transformation would be wrong, which the token form must leave alone too.
 * Every example is legal under Java's own semantics, exceptions included, for
 * the reason its section gives.
 */
public class Examples {

    static class Counter { int value; int other; }
    static class Logger { int count; }
    static class Link { Link next; }

    // Recursive, so inlining can't remove the call. It reads Link.next only.
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

    // Two implementations, both instantiated in main, so a call through Shape
    // can't be devirtualized. Each reads only its own fields.
    interface Shape { int area(); }
    static final class Square implements Shape { int side; public int area() { return side * side; } }
    static final class Rect implements Shape { int width, height; public int area() { return width * height; } }

    // --- dead stores ------------------------------------------------------
    // Nothing between the two stores can throw, so no exception handler can
    // see the first one. That rules out calls: any call can throw, if only a
    // StackOverflowError.

    // counter was dereferenced by the first store, so writing its other field
    // can't throw. Graal keeps the dead store, because its peephole wants the
    // overwrite to be the very next node. Needs per-field tokens.
    static void deadStoreOtherField(Counter counter) {
        counter.value = 1;
        counter.other = 7;
        counter.value = 2;
    }

    // Control: a read between through another reference, which may be the
    // same object, so it may see the first store. (A read through counter
    // itself would not do: forwarding it makes the store dead again.)
    static void deadStoreMaybeAliasControl(Counter counter, Counter alias) {
        counter.value = 1;
        counter.other = alias.value;
        counter.value = 2;
    }

    // The same with another object, read before the first store, so writing
    // to it can't throw a NullPointerException between the stores.
    static void deadStoreOtherObject(Counter counter, Logger logger) {
        int seen = logger.count;
        counter.value = 1;
        logger.count = seen + 1;
        counter.value = 2;
    }

    // Overwritten on both arms of a branch. Graal's peephole wants one usage
    // and the overwrite next; here there are two usages and the If. Needs no
    // more than one heap token.
    static void deadStoreBothArms(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        } else {
            counter.value = 2;
        }
    }

    // Control: overwritten on one arm only.
    static void deadStoreOneArm(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        }
    }

    // --- loads across calls -----------------------------------------------
    // If the call throws, the load after it never runs, so these are legal
    // whatever the call may throw. Graal misses them because a call kills
    // every location. They need a signature for the callee.

    // The load gets the stored 5: length doesn't write Counter.value.
    static int forwardAcrossCall(Counter counter, Link list) {
        counter.value = 5;
        int n = length(list);
        return counter.value + n;
    }

    // Control: countInto writes Counter.value.
    static int forwardAcrossCallControl(Counter counter, Link list) {
        counter.value = 5;
        countInto(counter, list);
        return counter.value;
    }

    // The load still gets the stored 5: this call writes, but only
    // Logger.count. Example II's call, with a load instead of the overwrite.
    static int forwardAcrossWritingCall(Counter counter, Logger logger, Link list) {
        counter.value = 5;
        countInto(logger, list);
        return counter.value;
    }

    // The second load repeats the first.
    static int repeatedLoadAcrossCall(Counter counter, Link list) {
        int before = counter.value;
        int n = length(list);
        return before + counter.value + n;
    }

    // Control: countInto writes Counter.value between the loads.
    static int repeatedLoadAcrossCallControl(Counter counter, Link list) {
        int before = counter.value;
        countInto(counter, list);
        return before + counter.value;
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

    // Control: countInto changes counter.value in every iteration.
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

    // --- calls ------------------------------------------------------------
    // Removing a call also removes the StackOverflowError it might throw, as
    // removing any dead code does. They need a signature showing the callee
    // only reads.

    // length's result is unused, and it only reads: the call can go.
    static void unusedReadOnlyCall(Link list) {
        length(list);
    }

    // Control: countInto writes, so it stays.
    static void unusedWritingCall(Counter counter, Link list) {
        countInto(counter, list);
    }

    // The second call repeats the first: nothing between writes Link.next.
    static int repeatedReadOnlyCall(Link list) {
        return length(list) + length(list);
    }

    // Control: the list changes between the calls.
    static int repeatedReadOnlyCallControl(Link list) {
        int first = length(list);
        if (list != null) {
            list.next = null;
        }
        return first + length(list);
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        Logger logger = new Logger();
        Link list = new Link();
        list.next = new Link();
        boolean flag = args.length > 0;
        Shape shape = flag ? new Square() : new Rect();

        deadStoreOtherField(counter);
        deadStoreMaybeAliasControl(counter, new Counter());
        deadStoreOtherObject(counter, logger);
        deadStoreBothArms(counter, flag);
        deadStoreOneArm(counter, flag);
        int sum = forwardAcrossCall(counter, list);
        sum += forwardAcrossCallControl(counter, list);
        sum += forwardAcrossWritingCall(counter, logger, list);
        sum += repeatedLoadAcrossCall(counter, list);
        sum += repeatedLoadAcrossCallControl(counter, list);
        sum += hoistLoadOutOfLoop(counter, list, 3);
        sum += hoistLoadOutOfLoopControl(counter, list, 3);
        sum += forwardAcrossVirtualCall(counter, shape);
        unusedReadOnlyCall(list);
        unusedWritingCall(counter, list);
        sum += repeatedReadOnlyCall(list);
        sum += repeatedReadOnlyCallControl(list);

        System.out.println(sum + counter.value + counter.other + logger.count);
    }
}
