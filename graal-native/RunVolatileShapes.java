/**
 * Runs VolatileShapes, prints what it computes as VolatileShapes does, and the time each shape took, the
 * best of many rounds, on the error stream, so that the round trip's comparison with the JVM sees only the results.
 */
public class RunVolatileShapes {
    public static void main(String[] args) {
        int rounds = 2_000_000 + args.length;
        int reps = Integer.getInteger("reps", 30);
        long[] best = new long[2];
        java.util.Arrays.fill(best, Long.MAX_VALUE);
        int[] result = new int[2];
        for (int r = 0; r < reps; r++) {
            long t0 = System.nanoTime();
            result[0] = VolatileShapes.inFields(rounds);
            long t1 = System.nanoTime();
            result[1] = VolatileShapes.inArray(rounds);
            long t2 = System.nanoTime();
            best[0] = Math.min(best[0], t1 - t0);
            best[1] = Math.min(best[1], t2 - t1);
        }
        System.out.println("fields " + result[0]);
        System.out.println("array " + result[1]);
        System.err.println("ms per " + rounds + " rounds: fields " + best[0] / 1_000_000.0 + " array " + best[1] / 1_000_000.0);
    }
}
