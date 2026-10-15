package conversion;

/**
 * Reading a field of a parameter: Java checks the reference for null first. Graal
 * branches to a block that makes the NullPointerException (BytecodeException) and
 * throws it (Unwind). In the token form that block is a λ marked `throws`: it gives
 * the exception back as `exc`, with every token.
 */
public class NullCheck {

    static class Box { int value; }

    static int demo(Box box) {
        return box.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Box());
    }
}
