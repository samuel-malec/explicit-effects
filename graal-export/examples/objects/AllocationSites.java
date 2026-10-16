public class AllocationSites {

    private static class A{ int value; }

    public static void demo(A a1, A a2) {
        a1.value = 6;
        a2.value = 7;
    }

    public static void main(String[] args) {
        A a1 = new A();
        A a2 = new A();
        demo(a1, a2);
        // A tmp = args.length > 0 ? a1 : a2;
        // demo(tmp);
    }
}
