package deadstores;

/**
 * Control for BothArms: only one arm overwrites, and the other returns, so the
 * caller may read the 0.
 */
public class OneArmKeeps {

    static class Counter { int value; }

    static void demo(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        }
    }

    public static void main(String[] args) {
        demo(new Counter(), args.length > 0);
    }
}
