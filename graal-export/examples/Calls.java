public class Calls {

    static class Counter {
        int value;

        void bump() {
            value++;
        }

        int bumpFrom(int start) {
            value = start;
            bump();
            return value;
        }
    }

    static int sum(int n) {
        return n <= 0 ? 0 : n + sum(n - 1);
    }

    public static void main(String[] args) {
        Counter c = new Counter();
        int n = c.bumpFrom(args.length);
        System.out.println(n + sum(n));
    }
}
