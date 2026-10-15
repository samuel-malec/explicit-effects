package conversion;

/**
 * A call with two possible targets. The translation calls an external, `dispatch …`,
 * that takes the tokens of both implementations: the call may do what either does,
 * so it takes h_side and h_radius.
 */
public class VirtualCall {

    interface Shape { void grow(); }

    static final class Square implements Shape {
        int side;
        public void grow() { side++; }
    }

    static final class Circle implements Shape {
        int radius;
        public void grow() { radius++; }
    }

    static void demo(Shape shape) {
        shape.grow();
    }

    public static void main(String[] args) {
        demo(args.length > 0 ? new Square() : new Circle());
    }
}
