import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

import com.oracle.graal.pointsto.PointsToAnalysis;
import com.oracle.graal.pointsto.flow.AccessFieldTypeFlow;
import com.oracle.graal.pointsto.flow.InvokeTypeFlow;
import com.oracle.graal.pointsto.flow.LoadFieldTypeFlow;
import com.oracle.graal.pointsto.flow.MethodFlowsGraph;
import com.oracle.graal.pointsto.flow.StoreFieldTypeFlow;
import com.oracle.graal.pointsto.flow.TypeFlow;
import com.oracle.graal.pointsto.meta.AnalysisField;
import com.oracle.graal.pointsto.meta.AnalysisMethod;
import com.oracle.graal.pointsto.meta.AnalysisUniverse;
import com.oracle.graal.pointsto.meta.PointsToAnalysisMethod;
import com.oracle.graal.pointsto.standalone.PointsToAnalyzer;

public class ReadWriteExport {

    /** Packages treated as "not the program under analysis" by default. */
    private static final String[] PLATFORM = {
                    "java.", "javax.", "jdk.", "sun.", "com.sun.",
                    "com.oracle.", "org.graalvm.",
    };

    private static boolean isUnderAnalysis(String className) {
        String filter = System.getProperty("dump.filter", "");
        if (filter.equals("*")) {
            return true;   // report everything, platform code included
        }
        if (!filter.isEmpty()) {
            return className.startsWith(filter);
        }
        for (String prefix : PLATFORM) {
            if (className.startsWith(prefix)) {
                return false;
            }
        }
        return true;
    }

    public static void main(String[] args) {
        PointsToAnalyzer analyzer = PointsToAnalyzer.createAnalyzer(args);
        analyzer.run();
        AnalysisUniverse universe = analyzer.getResultUniverse();

        TreeMap<String, TreeSet<String>> reads = new TreeMap<>();
        TreeMap<String, TreeSet<String>> writes = new TreeMap<>();
        TreeMap<String, TreeSet<String>> callees = new TreeMap<>();
        PointsToAnalysis bb = analyzer.getResultAnalysis();
        TreeSet<String> analysed = new TreeSet<>();

        for (AnalysisMethod method : universe.getMethods()) {
            if (!method.isReachable() || !(method instanceof PointsToAnalysisMethod ptm)) {
                continue;
            }
            if (!ptm.getTypeFlow().flowsGraphCreated()) {
                continue;
            }
            String owner = method.getDeclaringClass().toJavaName(true);
            if (!isUnderAnalysis(owner)) {
                continue;
            }
            String name = GraphExport.methodKey(method);
            if (ptm.ensureGraphParsed(bb).getEncodedGraph() != null) {
                analysed.add(name);
            }
            // NB: flows(), not getNodeFlows() -- store flows live in
            // miscEntryFlows, and getNodeFlows() silently yields no writes.
            MethodFlowsGraph graph = ptm.getTypeFlow().getMethodFlowsGraph();
            for (TypeFlow<?> flow : graph.flows()) {
                if (flow instanceof AccessFieldTypeFlow access) {
                    AnalysisField field = access.field();
                    String fq = field.getDeclaringClass().toJavaName(true) + "." + field.getName();
                    if (flow instanceof LoadFieldTypeFlow) {
                        reads.computeIfAbsent(name, k -> new TreeSet<>()).add(fq);
                    } else if (flow instanceof StoreFieldTypeFlow) {
                        writes.computeIfAbsent(name, k -> new TreeSet<>()).add(fq);
                    }
                }
            }

            // The call graph, points-to resolved: a virtual call yields every
            // target the analysis considers possible, not just the declared
            // one. This is what the prototype's transitive closure consumes.
            for (InvokeTypeFlow invoke : graph.getInvokes()) {
                for (AnalysisMethod callee : invoke.getOriginalCallees()) {
                    String target = GraphExport.methodKey(callee);
                    callees.computeIfAbsent(name, k -> new TreeSet<>()).add(target);
                }
            }
        }

        Set<String> all = new TreeSet<>();
        all.addAll(reads.keySet());
        all.addAll(writes.keySet());

        System.out.println();
        System.out.println("=== local per-method field effects ===");
        if (all.isEmpty()) {
            System.out.println("  (nothing reported -- wrong -Ddump.filter, or no reachable");
            System.out.println("   field accesses in the analysed program?)");
        }
        for (String m : all) {
            System.out.printf("  %-34s reads=%-28s writes=%s%n",
                            m,
                            reads.getOrDefault(m, new TreeSet<>()),
                            writes.getOrDefault(m, new TreeSet<>()));
        }

        System.out.println();
        System.out.println("=== call graph with points-to resolved callees ===");
        for (String m : new TreeSet<>(callees.keySet())) {
            TreeSet<String> targets = new TreeSet<>();
            for (String t : callees.get(m)) {
                // keep platform callees out of the listing, but note them
                targets.add(isUnderAnalysis(t.substring(0, t.lastIndexOf('.', t.indexOf('(')))) ? t : "<platform>");
            }
            targets.remove("<platform>");
            if (!targets.isEmpty()) {
                System.out.printf("  %-34s -> %s%n", m, targets);
            }
        }

        System.out.println();
        System.out.println("=== reachable fields ===");
        TreeMap<String, boolean[]> fields = new TreeMap<>();
        for (AnalysisField f : universe.getFields()) {
            String owner = f.getDeclaringClass().toJavaName(true);
            if (!isUnderAnalysis(owner)) {
                continue;
            }
            fields.put(owner + "." + f.getName(), new boolean[]{f.isRead(), f.isWritten()});
        }
        for (var e : fields.entrySet()) {
            System.out.printf("  %-30s read=%-6s written=%s%n",
                            e.getKey(), e.getValue()[0], e.getValue()[1]);
        }

        String facts = factsJson(analysed, reads, writes, callees, fields);
        String jsonPath = System.getProperty("dump.json", "");
        if (!jsonPath.isEmpty()) {
            write(jsonPath, "{\n" + facts + "\n}\n");
            System.out.println();
            System.out.println("wrote " + jsonPath);
        }

        // The IR, for the token-form conversion. A superset of the effects
        // JSON (same "methods" and "fields"), so one file carries both the
        // facts the signatures are derived from and the graphs they apply to.
        String irPath = System.getProperty("dump.ir", "");
        if (!irPath.isEmpty()) {
            List<Map<String, Object>> graphs = new ArrayList<>();
            for (AnalysisMethod method : universe.getMethods()) {
                if (method.isReachable() && method instanceof PointsToAnalysisMethod ptm && ptm.getTypeFlow().flowsGraphCreated() &&
                                isUnderAnalysis(method.getDeclaringClass().toJavaName(true))) {
                    graphs.add(GraphExport.export(bb, ptm));
                }
            }
            graphs.sort((a, b) -> (a.get("name") + " " + a.get("descriptor")).compareTo(b.get("name") + " " + b.get("descriptor")));
            write(irPath, "{\n" + facts + ",\n  \"graphs\": " + GraphExport.toJson(graphs, 1) + "\n}\n");
            System.out.println();
            System.out.println("wrote " + graphs.size() + " graphs to " + irPath);
        }
    }

    /**
     * Machine-readable form, for the prototype's partitioner/derivation to
     * consume. Hand-rolled so this stays dependency-free. Returns the members
     * without the enclosing braces, so the IR dump can add its own.
     */
    private static String factsJson(Set<String> methods,
                    TreeMap<String, TreeSet<String>> reads,
                    TreeMap<String, TreeSet<String>> writes,
                    TreeMap<String, TreeSet<String>> callees,
                    TreeMap<String, boolean[]> fields) {
        Set<String> allMethods = new TreeSet<>(methods);
        allMethods.addAll(callees.keySet());
        StringBuilder sb = new StringBuilder();
        sb.append("  \"methods\": {\n");
        boolean firstMethod = true;
        for (String m : allMethods) {
            if (!firstMethod) {
                sb.append(",\n");
            }
            firstMethod = false;
            sb.append("    \"").append(m).append("\": {")
                            .append("\"reads\": ").append(jsonArray(reads.get(m)))
                            .append(", \"writes\": ").append(jsonArray(writes.get(m)))
                            .append(", \"callees\": ").append(jsonArray(callees.get(m)))
                            .append("}");
        }
        sb.append("\n  },\n  \"fields\": {\n");
        boolean firstField = true;
        for (var e : fields.entrySet()) {
            if (!firstField) {
                sb.append(",\n");
            }
            firstField = false;
            sb.append("    \"").append(e.getKey()).append("\": {")
                            .append("\"read\": ").append(e.getValue()[0])
                            .append(", \"written\": ").append(e.getValue()[1])
                            .append("}");
        }
        sb.append("\n  }");
        return sb.toString();
    }

    private static void write(String path, String content) {
        try {
            java.nio.file.Path out = java.nio.file.Path.of(path).toAbsolutePath();
            java.nio.file.Path parent = out.getParent();
            if (parent != null) {
                java.nio.file.Files.createDirectories(parent);
            }
            java.nio.file.Files.writeString(out, content);
        } catch (java.io.IOException e) {
            throw new RuntimeException("could not write " + path, e);
        }
    }

    private static String jsonArray(Set<String> values) {
        if (values == null || values.isEmpty()) {
            return "[]";
        }
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (String v : values) {
            if (!first) {
                sb.append(", ");
            }
            first = false;
            sb.append('"').append(v).append('"');
        }
        return sb.append(']').toString();
    }
}
