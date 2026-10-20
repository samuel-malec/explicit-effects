package objects;

/**
 * The call writes Counter.value, but only ever of the other counter: with object
 * partitions its signature names only that object's partition, so the call doesn't
 * take the token of counter.value, and the load takes the 5. 
 */
public class CallOnOtherObject {

    static class Counter { int value; }
    static class Link { Link next; }

    // Recursive, so that Graal can't inline it before the analysis.
    static void countInto(Counter counter, Link link) {
        if (link != null) {
            counter.value++;
            countInto(counter, link.next);
        }
    }

    static int demo(Counter counter, Counter other, Link list) {
        counter.value = 5;
        countInto(other, list);
        return counter.value;
    }

    static int sink;

    public static void main(String[] args) {
        sink = demo(new Counter(), new Counter(), new Link());
    }
}
