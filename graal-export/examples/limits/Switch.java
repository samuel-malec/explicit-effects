package limits;

/**
 * A switch: Graal's IntegerSwitch has more than two successors, and the translation
 * only knows two-way branches, so it refuses the method. A chain of two-way branches
 * would do; it isn't written yet.
 */
public class Switch {

    static int low;
    static int middle;
    static int high;

    static void demo(int k) {
        switch (k) {
            case 0 -> low++;
            case 1 -> middle++;
            case 2 -> high++;
            default -> { }
        }
    }

    public static void main(String[] args) {
        demo(args.length);
    }
}
