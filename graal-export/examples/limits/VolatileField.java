package limits;

/**
 * A volatile access orders memory with other threads, which the tokens don't model:
 * the translation refuses the method, and the facts make every caller touch
 * everything.
 */
public class VolatileField {

    static volatile int flag;

    static int demo() {
        return flag;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo();
    }
}
