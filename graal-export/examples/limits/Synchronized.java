package limits;

/**
 * A lock: entering and leaving a monitor lets this thread see what other threads
 * wrote. The translation refuses the method, at Graal's MonitorId, the node that
 * names the lock.
 */
public class Synchronized {

    static final Object LOCK = new Object();
    static int count;

    static void demo() {
        synchronized (LOCK) {
            count++;
        }
    }

    public static void main(String[] args) {
        demo();
    }
}
