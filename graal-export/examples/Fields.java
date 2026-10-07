public class Fields {

    static class Point {
        int x;
        int y;

        int shift(int dx) {
            int moved = x + dx;
            x = moved;
            y = moved;
            return moved;
        }
    }

    public static void main(String[] args) {
        Point p = new Point();
        System.out.println(p.shift(args.length));
    }
}
