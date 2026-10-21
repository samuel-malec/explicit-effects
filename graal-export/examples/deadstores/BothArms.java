package deadstores;

/**
 * Both arms of the branch overwrite the field before anything reads it.
 */
public class BothArms {

    static class Counter { int value; }

    static void demo(Counter counter, boolean flag) {
        counter.value = 0;
        if (flag) {
            counter.value = 1;
        } else {
            counter.value = 2;
        }
    }

    public static void main(String[] args) {
        demo(new Counter(), args.length > 0);
    }
}
