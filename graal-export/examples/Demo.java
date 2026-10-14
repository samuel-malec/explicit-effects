public class Demo {

    static class A { int value; int other; }
    static class B { int count; }   
    static class Node{ Node next; }

    private static void countInto(B b, Node node) {
        if (node != null) {
            b.count++;
            countInto(b, node.next);
        }
    }

    static int foo(A a, B b, Node node) {
        a.value = 5;
        countInto(b, node); // accesses -> B::count, Node::next  
        return a.value;
    }

    static void storeChain(A a, B b) {
        a.value = 6;
        a.other = 7;
        b.count = 8;
    }

    static void maybeAlias(A a1, A a2, B b) {
        a1.value = 6;
        a2.value = 7;
        b.count = 8;
    }


    public static void main(String[] args) {
        A a1 = new A();
        A a2 = new A();
        B b = new B();
        Node node = new Node();
        storeChain(a1, b);
        foo(a1, b, node);
        maybeAlias(a1, a2, b);
    }
}