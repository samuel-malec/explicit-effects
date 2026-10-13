class PartitionDemo {

    private static class A {
        int value;
    }

    private static class B {
        int sus;
    }

    private static class Node {
        Node next;
    }

    // Written like this in order to avoid inlining and also tail call optimization
    private static int getLength(Node n) {
        if (n == null) {
            return 0;
        }
        return 1 + getLength(n.next);
    }

    private static void work(A a, B b) {
        a.value = 5;
        b.sus = 10;
        a.value = 15;
    }

    private static void main(String[] args) {
        A a = new A();
        B b = new B();
        work(a, b);
        System.out.println(a.value);
    }
}
