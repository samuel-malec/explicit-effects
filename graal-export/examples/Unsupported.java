/** What the translation refuses today. */
public class Unsupported {

    static class Box {
        int v;
        volatile int flag;

        synchronized void add(int n) {
            v += n;
        }
    }

    interface Shape {
        int area();
    }

    static final class Square implements Shape {
        int side;

        public int area() {
            return side * side;
        }
    }

    static final class Rect implements Shape {
        int width;
        int height;

        public int area() {
            return width * height;
        }
    }

    // An array access.
    static int first(int[] a) {
        return a[0];
    }

    // An allocation that escape analysis keeps.
    static Box make() {
        return new Box();
    }

    // A call with two possible targets.
    static int area(Shape s) {
        return s.area();
    }

    // A volatile store.
    static void publish(Box b) {
        b.flag = 1;
    }

    public static void main(String[] args) {
        Box b = make();
        b.add(args.length);
        publish(b);
        Shape s = args.length > 0 ? new Square() : new Rect();
        System.out.println(first(new int[] {args.length}) + area(s));
    }
}
