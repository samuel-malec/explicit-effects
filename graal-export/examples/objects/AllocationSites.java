package objects;

public class AllocationSites {

    private static class A{ int value; }
    static class Link{ Link next; }

    static int length(Link link) {
        return link == null ? 0 : 1 + length(link.next);
    }

    public static int demo(A a1, A a2, Link link) {
        a1.value = 6;
        length(link);
        a2.value = 7;
        return a1.value + a2.value;
    }

    static int sink;

    public static void main(String[] args) {
        A a1 = new A();
        A a2 = new A();
        sink = demo(a1, a2, new Link());
    }
}
