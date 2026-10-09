public class Counter {

    private static class Node {
        Node next;
    }

    private static class A {
        int value;

        public A(int value) {
            this.value = value;
        }
    }

    private static class B {
        A ref;

        public B(A ref) {
            this.ref = ref;
        }
    }

    private static class C {
        A ref;

        public C(A ref) {
            this.ref = ref;
        }
    }


    private static int length(Node node) {
        if (node == null ) {
            return 0;
        }

        return 1 + length(node.next);
    }


    private static int work(B b, C c, Node node) {
        int len = length(node);
        b.ref.value = 20;
        System.out.println(c.ref.value);
        return len + c.ref.value;
    }

    public static void main(String[] args) {
        A a = new A(10);
        B b = new B(a);
        C c = new C(a);
        a.value = 15;
        Node na = new Node();
        Node nb = new Node();
        na.next = nb;
        System.out.println(work(b, c, na));
    }
}
