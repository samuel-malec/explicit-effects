/**
 * Runs every Are We Fast Yet benchmark, constructed directly so that a
 * closed-world analysis sees them all: the suite's own harness picks one by
 * name, through reflection. Whether each verified goes to standard output and
 * its run times to standard error, so that the output compares exactly across
 * builds.
 *
 *   java -cp classes Awfy             # the suite's test sizes, once each
 *   java -cp classes Awfy 10 timing   # the sizes it benchmarks with, 10 times each
 */
public final class Awfy {

    /** A benchmark, its size for the suite's tests, and its size for timing (test.conf and rebench.conf). */
    private record Entry(String name, Benchmark benchmark, int test, int timing) {
    }

    public static void main(String[] args) {
        int iterations = args.length > 0 ? Integer.parseInt(args[0]) : 1;
        boolean timing = args.length > 1 && args[1].equals("timing");
        Entry[] entries = {
            new Entry("Bounce", new Bounce(), 1, 1500),
            new Entry("CD", new CD(), 10, 250),
            new Entry("DeltaBlue", new DeltaBlue(), 1, 12000),
            new Entry("Havlak", new Havlak(), 1, 1500),
            new Entry("Json", new Json(), 1, 100),
            new Entry("List", new List(), 1, 1500),
            new Entry("Mandelbrot", new Mandelbrot(), 1, 500),
            new Entry("NBody", new NBody(), 1, 250000),
            new Entry("Permute", new Permute(), 1, 1000),
            new Entry("Queens", new Queens(), 1, 1000),
            new Entry("Richards", new Richards(), 1, 100),
            new Entry("Sieve", new Sieve(), 1, 3000),
            new Entry("Storage", new Storage(), 1, 1000),
            new Entry("Towers", new Towers(), 1, 600),
        };
        for (Entry entry : entries) {
            int size = timing ? entry.timing() : entry.test();
            for (int i = 0; i < iterations; i++) {
                long start = System.nanoTime();
                boolean verified = entry.benchmark().innerBenchmarkLoop(size);
                System.err.println(entry.name() + " " + (System.nanoTime() - start) / 1000 + "us");
                if (!verified) {
                    System.out.println(entry.name() + ": incorrect result");
                    System.exit(1);
                }
            }
            System.out.println(entry.name() + ": ok");
        }
    }
}
