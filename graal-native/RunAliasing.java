/**
 * Runs Aliasing and prints what it computed. Aliasing keeps the result to
 * itself, so that its export stays small; the native image has to show it.
 */
public class RunAliasing {
    public static void main(String[] args) {
        Aliasing.main(args);
        System.out.println(Aliasing.result);
    }
}
