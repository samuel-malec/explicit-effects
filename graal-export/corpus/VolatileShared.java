/**
 * A volatile flag a thread waits on, which another thread raises. Reading it as a plain field lets the
 * wait loop read it once, and the program never ends: the flag is in a static field, every thread
 * reaches it, and its accesses must stay volatile. The control: claim the wait loop's read is of an
 * object only one thread reaches (LIE_LOCKS='VolatileShared.waitForFlag()I' to graal-native/run.sh, mode
 * locks); the program must then hang (exit 124).
 */
public class VolatileShared {

    static class Flag {
        volatile boolean raised;
    }

    static final Flag FLAG = new Flag();

    static int waitForFlag() {
        int spins = 0;
        while (!FLAG.raised) {
            spins++;
        }
        return spins >= 0 ? 1 : 0;
    }

    public static void main(String[] args) throws InterruptedException {
        Thread worker = new Thread(() -> {
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                return;
            }
            FLAG.raised = true;
        });
        worker.start();
        System.out.println("flag " + waitForFlag());
        worker.join();
    }
}
