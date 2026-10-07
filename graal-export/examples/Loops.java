public class Loops {

    static class Counter {
        int value;

        void addUpTo(int n) {
            for (int i = 0; i < n; i++) {
                value += i;
            }
        }
    }

    public static void main(String[] args) {
        Counter c = new Counter();
        c.addUpTo(args.length + 3);
        System.out.println(c.value);
    }
}
