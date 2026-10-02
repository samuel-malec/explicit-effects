// Run with DUMP_FILTER=* to report every reachable method, or
// DUMP_FILTER=org.graalvm.collections for just the graal library.
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.graalvm.collections.EconomicMap;
import org.graalvm.collections.EconomicSet;
import org.graalvm.collections.Pair;
import org.graalvm.collections.UnmodifiableEconomicMap;

public class Bench {

    static class Item {
        final String name;
        int score;
        Item next;

        Item(String name, int score) {
            this.name = name;
            this.score = score;
        }
    }

    static String key(String prefix, int i) {
        return prefix.concat(String.valueOf(i));
    }

    static EconomicMap<String, Item> buildEconomic(int n) {
        EconomicMap<String, Item> map = EconomicMap.create();
        for (int i = 0; i < n; i++) {
            String k = key("k", i);
            map.put(k, new Item(k, i * 3));
        }
        return map;
    }

    static int sumEconomic(UnmodifiableEconomicMap<String, Item> map) {
        int total = 0;
        for (Item item : map.getValues()) {
            total += item.score;
        }
        return total;
    }

    static EconomicSet<String> namesOf(UnmodifiableEconomicMap<String, Item> map) {
        EconomicSet<String> names = EconomicSet.create();
        for (String k : map.getKeys()) {
            names.add(k);
        }
        return names;
    }

    static Item chain(List<Item> items) {
        Item head = null;
        for (int i = 0; i < items.size(); i++) {
            Item item = items.get(i);
            item.next = head;
            head = item;
        }
        return head;
    }

    static int walk(Item head) {
        int total = 0;
        for (Item cursor = head; cursor != null; cursor = cursor.next) {
            total += cursor.score;
        }
        return total;
    }

    static Map<String, Integer> tally(List<Item> items) {
        Map<String, Integer> counts = new HashMap<>();
        for (int i = 0; i < items.size(); i++) {
            Item item = items.get(i);
            Integer seen = counts.get(item.name);
            int base = seen == null ? 0 : seen.intValue();
            counts.put(item.name, Integer.valueOf(base + item.score));
        }
        return counts;
    }

    public static void main(String[] args) {
        int n = args.length > 0 ? Integer.parseInt(args[0]) : 64;

        EconomicMap<String, Item> economic = buildEconomic(n);
        int economicSum = sumEconomic(economic);
        int nameCount = namesOf(economic).size();

        List<Item> items = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            items.add(new Item(key("i", i % 8), i));
        }
        int chained = walk(chain(items));
        int tallied = tally(items).size();

        Pair<Integer, Integer> pair = Pair.create(Integer.valueOf(economicSum),
                        Integer.valueOf(chained));
        StringBuilder out = new StringBuilder();
        out.append(pair.getLeft().intValue()).append('/').append(pair.getRight().intValue());
        out.append(' ').append(nameCount).append(' ').append(tallied);
        System.out.println(out.toString());
    }
}
