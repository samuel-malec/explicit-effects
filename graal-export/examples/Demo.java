public class Demo {

    static class Counter { int value; }
    static class Config  { int limit; }
    static class Logger  { int count; }

    // --- Example I -------------------------------------------------------
    static void bump(Counter counter) {
        counter.value++;
    }

    static void process(Counter counter, Config config, int n) {
        for (int i = 0; i < n; i++) {
            bump(counter);
            if (i > config.limit) {
                break;
            }
        }
    }

    // --- Example II ------------------------------------------------------
    static void unrelatedWork(Logger logger) {
        logger.count++;
    }

    static void resetCounter(Counter counter, Logger logger) {
        counter.value = 1;
        unrelatedWork(logger);
        counter.value = 2;
    }

    public static void main(String[] args) {
        Counter counter = new Counter();
        Config config = new Config();
        Logger logger = new Logger();
        config.limit = 10;
        process(counter, config, 10);
        resetCounter(counter, logger);
        System.out.println(counter.value + logger.count);
    }
}
