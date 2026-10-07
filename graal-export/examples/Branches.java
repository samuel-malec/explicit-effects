public class Branches {

    static class Counter {
        int value;

        void reset(boolean flag) {
            value = 0;
            if (flag) {
                value = 1;
            } else {
                value = 2;
            }
        }

        int step(boolean up) {
            int next;
            if (up) {
                next = value + 1;
                value = next;
            } else {
                next = value - 1;
                value = next;
            }
            return next * 2;
        }
    }

    public static void main(String[] args) {
        Counter c = new Counter();
        boolean flag = args.length > 0;
        c.reset(flag);
        System.out.println(c.step(flag));
    }
}
