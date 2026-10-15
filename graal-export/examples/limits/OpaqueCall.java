package limits;

/**
 * A call the facts can't say anything about, here a native method: it may touch any
 * memory, so its signature is opaque and the call takes every token of the caller,
 * even with --partition field. Nothing is forwarded or removed across it.
 */
public class OpaqueCall {

    static long last;

    static void demo() {
        last = System.nanoTime();
    }

    public static void main(String[] args) {
        demo();
    }
}
