package conversion;

/**
 * A branch whose arms write different fields. Each arm is a λ; the branch picks one
 * with opt/opt/join and calls it through a frame, which forks every token so both
 * candidates are typed, though only one runs. Both arms jump to the merge, a λ that
 * takes the tokens back as parameters.
 */
public class IfElse {

    static int hits;
    static int misses;

    static void demo(boolean hit) {
        if (hit) {
            hits++;
        } else {
            misses++;
        }
    }

    public static void main(String[] args) {
        demo(args.length > 0);
    }
}
