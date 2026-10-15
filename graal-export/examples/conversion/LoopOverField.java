package conversion;

/**
 * A loop that updates a static field in every iteration: the field's token goes
 * around the loop as a parameter of the header λ, as Graal's memory would through a
 * memory phi, and each iteration's load and store take the next version.
 */
public class LoopOverField {

    static int total;

    static void demo(int n) {
        for (int i = 0; i < n; i++) {
            total += i;
        }
    }

    public static void main(String[] args) {
        demo(args.length + 3);
    }
}
