public class Allocation {

    static final class Box {
        final int value;

        Box(int value) {
            this.value = value;
        }
    }

    static Box[] kept;
    static Object sink;

    // Allocates enough to collect, which resets the thread's allocation buffer. It writes
    // Allocation.sink and byte arrays, and reaches nothing that may write anything else.
    static void churn(int n) {
        for (int i = 0; i < n; i++) {
            sink = new byte[4096];
        }
    }

    // The first box escapes before the call, so it is allocated there; the second after it.
    static void across(int i, int n) {
        Box first = new Box(i);
        kept[2 * i] = first;
        churn(n);
        Box second = new Box(-i);
        kept[2 * i + 1] = second;
    }

    public static void main(String[] args) {
        int count = 2000 + args.length;
        kept = new Box[2 * count];
        for (int i = 0; i < count; i++) {
            across(i, 64);
        }
        long sum = 0;
        int wrong = 0;
        for (int i = 0; i < count; i++) {
            Box first = kept[2 * i];
            Box second = kept[2 * i + 1];
            wrong += first.value == i && second.value == -i ? 0 : 1;
            sum += first.value - second.value;
        }
        System.out.println(sum + " " + wrong);
    }
}
