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

    static int forwardAcrossCall(Counter counter, Link list) {
        counter.value = 5;
        int n = length(list); // length(list) doesn't touch Counter.value, yet
        return counter.value + n;  // Graal produces redundant load here
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
