/**
 * Runs LockShapes, prints what it computes as LockShapes does, and the time each shape took, the best of
 * many rounds, on the error stream, so that the round trip's comparison with the JVM sees only the results.
 */
public class RunLockShapes {
    public static void main(String[] args) {
        int rounds = 2_000_000 + args.length;
        int reps = Integer.getInteger("reps", 30);
        long[] best = new long[5];
        java.util.Arrays.fill(best, Long.MAX_VALUE);
        int[] result = new int[5];
        for (int r = 0; r < reps; r++) {
            long t0 = System.nanoTime();
            result[0] = LockShapes.inFields(rounds);
            long t1 = System.nanoTime();
            result[1] = LockShapes.inArray(rounds);
            long t2 = System.nanoTime();
            result[2] = LockShapes.inList(rounds);
            long t3 = System.nanoTime();
            result[3] = LockShapes.throughCalls(rounds);
            long t4 = System.nanoTime();
            result[4] = LockShapes.inBuffer(rounds);
            long t5 = System.nanoTime();
            best[0] = Math.min(best[0], t1 - t0);
            best[1] = Math.min(best[1], t2 - t1);
            best[2] = Math.min(best[2], t3 - t2);
            best[3] = Math.min(best[3], t4 - t3);
            best[4] = Math.min(best[4], t5 - t4);
        }
        System.out.println("fields " + result[0]);
        System.out.println("array " + result[1]);
        System.out.println("list " + result[2]);
        System.out.println("calls " + result[3]);
        System.out.println("buffer " + result[4]);
        String[] names = {"fields", "array", "list", "calls", "buffer"};
        StringBuilder text = new StringBuilder("ms per " + rounds + " rounds:");
        for (int i = 0; i < names.length; i++) {
            text.append(' ').append(names[i]).append(' ').append(best[i] / 1_000_000.0);
        }
        System.err.println(text);
    }
}
