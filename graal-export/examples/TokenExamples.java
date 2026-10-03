public class TokenExamples {

    static class Counter { int value; }
    static class Config  { int limit; }
    static class Logger  { int count; }

    static void unrelatedWork(Logger logger) { logger.count++; }
    static void note(Logger logger) { logger.count++; }
    static void bump(Counter counter) { counter.value++; }
    static void bump(Counter counter, int by) { counter.value += by; }
    static int peek(Counter counter) { return counter.value; }

    // --- dead stores ------------------------------------------------------
    static void resetCounter(Counter counter, Logger logger) {
        counter.value = 1;
        unrelatedWork(logger);
        counter.value = 2;
    }

    // Control: the callee reads counter.value, so the first store is live.
    static void resetCounterPeek(Counter counter, Logger logger) {
        counter.value = 1;
        peek(counter);
        counter.value = 2;
    }

    // Control: nothing at all between the two stores.
    static void resetCounterAdjacent(Counter counter) {
        counter.value = 1;
        counter.value = 2;
    }

    // Branches: the first store is overwritten on both arms.
    static void resetEitherWay(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        } else {
            counter.value = 2;
        }
    }

    // Control: overwritten on one arm only.
    static void resetOneWay(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        }
    }

    // --- store-to-load forwarding -----------------------------------------

    // The load's token comes straight from the store.
    static int readBack(Counter counter, Logger logger) {
        counter.value = 5;
        unrelatedWork(logger);
        return counter.value;
    }

    // Control: the call writes counter.value in between.
    static int readBackBump(Counter counter) {
        counter.value = 5;
        bump(counter);
        return counter.value;
    }

    // Merge: the load sees one of two stores, so there is no single value.
    // The call is what keeps the load alive: without it, the read elimination
    // in the partial escape analysis that runs before points-to already
    // replaces the load with a phi of 1 and 2.
    static int readAfterBranch(Counter counter, Logger logger, boolean flag) {
        if (flag) {
            counter.value = 1;
        } else {
            counter.value = 2;
        }
        unrelatedWork(logger);
        return counter.value;
    }

    // --- independent calls ------------------------------------------------

    // The two calls share no token.
    static void tick(Counter counter, Logger logger) {
        bump(counter);
        note(logger);
    }

    // Control: both calls touch Counter.
    static void tickTwice(Counter counter) {
        bump(counter);
        bump(counter);
    }

    // Overloads: each call names its own bump, by descriptor.
    static void bumpOverloads(Counter counter) {
        bump(counter);
        bump(counter, 2);
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        Config config = new Config();
        Logger logger = new Logger();
        boolean flag = args.length > 0;
        config.limit = 10;

        resetCounter(counter, logger);
        resetCounterPeek(counter, logger);
        resetCounterAdjacent(counter);
        resetEitherWay(counter, flag);
        resetOneWay(counter, flag);
        int sum = readBack(counter, logger);
        sum += readBackBump(counter);
        sum += readAfterBranch(counter, logger, flag);
        tick(counter, logger);
        tickTwice(counter);
        bumpOverloads(counter);

        System.out.println(sum + counter.value + logger.count);
    }
}
