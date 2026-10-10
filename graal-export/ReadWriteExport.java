import java.io.OutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.HashMap;
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

import jdk.graal.compiler.graph.Node;
import jdk.graal.compiler.nodes.Invoke;
import jdk.graal.compiler.nodes.StartNode;
import jdk.graal.compiler.nodes.StructuredGraph;
import jdk.graal.compiler.nodes.ValueNode;
import jdk.graal.compiler.nodes.java.AbstractNewObjectNode;
import jdk.graal.compiler.nodes.java.AccessFieldNode;
import jdk.graal.compiler.nodes.extended.BytecodeExceptionNode;
import jdk.graal.compiler.nodes.java.AccessIndexedNode;
import jdk.graal.compiler.nodes.java.ArrayLengthNode;
import jdk.graal.compiler.nodes.java.ExceptionObjectNode;
import jdk.graal.compiler.nodes.java.FinalFieldBarrierNode;
import jdk.graal.compiler.nodes.java.LoadFieldNode;
import jdk.graal.compiler.nodes.java.LoadIndexedNode;
import jdk.graal.compiler.nodes.memory.MemoryAccess;
import jdk.graal.compiler.nodes.memory.MemoryKill;
import jdk.graal.compiler.nodes.virtual.CommitAllocationNode;
import jdk.graal.compiler.replacements.nodes.BasicArrayCopyNode;
import jdk.vm.ci.meta.JavaKind;

public class ReadWriteExport {

    /** Packages treated as "not the program under analysis" by default. */
    private static final String[] PLATFORM = {
                    "java.", "javax.", "jdk.", "sun.", "com.sun.",
                    "com.oracle.", "org.graalvm.",
                    // the JDK's own packages outside java.*: security (GSS-API),
                    // XML signatures, DOM and SAX
                    "org.ietf.", "org.jcp.", "org.w3c.", "org.xml.",
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
        // Through Object, so that verifying this class doesn't load the standalone
        // analysis: a native-image build has none, and exports its own.
        PointsToAnalysis bb = (PointsToAnalysis) (Object) analyzer.getResultAnalysis();
        export(bb, analyzer.getResultUniverse(), System.getProperty("dump.json", ""), System.getProperty("dump.ir", ""), System.out);
    }

    /**
     * Exports the facts of every reachable method, and the graphs of the program's, from an
     * analysis that has run: the standalone analyzer's, or Native Image's own, from a feature.
     * An empty path skips that file; the reports go to {@code report}, null for none.
     */
    public static void export(PointsToAnalysis bb, AnalysisUniverse universe, String jsonPath, String irPath, PrintStream report) {
        PrintStream out = report != null ? report : new PrintStream(OutputStream.nullOutputStream());
        TreeMap<String, TreeSet<String>> reads = new TreeMap<>();
        TreeMap<String, TreeSet<String>> writes = new TreeMap<>();
        TreeMap<String, TreeSet<String>> callees = new TreeMap<>();
        TreeSet<String> analysed = new TreeSet<>();
        TreeSet<String> program = new TreeSet<>();
        TreeSet<String> allocates = new TreeSet<>();
        TreeMap<String, TreeSet<String>> unknown = new TreeMap<>();
        TreeMap<String, TreeSet<String>> unresolved = new TreeMap<>();
        TreeMap<String, TreeSet<String>> accesses = new TreeMap<>();

        for (AnalysisMethod method : universe.getMethods()) {
            if (!method.isReachable() || !(method instanceof PointsToAnalysisMethod ptm)) {
                continue;
            }
            if (!ptm.getTypeFlow().flowsGraphCreated()) {
                continue;
            }
            String name = GraphExport.methodKey(method);
            if (isUnderAnalysis(method.getDeclaringClass().toJavaName(true))) {
                program.add(name);
            }
            
            StructuredGraph body;
            try {
                body = GraphExport.analysisGraph(bb, ptm);
            } catch (VirtualMachineError e) {
                throw e;
            } catch (Throwable t) {
                // Decoding a graph again after the analysis fails where a plugin only runs before
                // Native Image seals its registries: then the method may touch anything.
                add(unknown, name, "no graph after the analysis (" + t.getClass().getSimpleName() + ")");
                body = null;
            }
            if (body != null) {
                analysed.add(name);
                Map<Integer, InvokeTypeFlow> flows = new HashMap<>();
                for (InvokeTypeFlow flow : ptm.getTypeFlow().getMethodFlowsGraph().getInvokes()) {
                    flows.put(flow.getBci(), flow);
                }
                // What each access's receiver may point to, for the program's
                // own methods: a field or array access elsewhere may touch any
                // object with the field or of the kind.
                GraphExport.PointsTo pointsTo = program.contains(name) ? new GraphExport.PointsTo(bb, ptm) : null;
                for (Node n : body.getNodes()) {
                    String at = " at bci " + (n instanceof ValueNode value ? GraphExport.bci(value) : -1);
                    if (n instanceof AccessFieldNode access) {
                        String field = GraphExport.fieldName(access.field());
                        add(access instanceof LoadFieldNode ? reads : writes, name, field);
                        if (pointsTo != null) {
                            addAccess(accesses, name, access instanceof LoadFieldNode ? "read" : "write", field, pointsTo.receivers(access), access);
                        }
                        if (access.ordersMemoryAccesses()) {
                            add(unknown, name, "volatile access to " + field + at);
                        }
                    } else if (n instanceof AccessIndexedNode access) {
                        add(access instanceof LoadIndexedNode ? reads : writes, name, arrayPartition(access.elementKind()));
                        if (pointsTo != null) {
                            addAccess(accesses, name, access instanceof LoadIndexedNode ? "read" : "write", arrayPartition(access.elementKind()), pointsTo.receivers(access), access);
                        }
                    } else if (n instanceof BasicArrayCopyNode copy && copy.getElementKind() != null) {
                        add(reads, name, arrayPartition(copy.getElementKind()));
                        add(writes, name, arrayPartition(copy.getElementKind()));
                        if (pointsTo != null) {
                            addAccess(accesses, name, "read", arrayPartition(copy.getElementKind()), pointsTo.objects(copy.getSource()), copy);
                            addAccess(accesses, name, "write", arrayPartition(copy.getElementKind()), pointsTo.objects(copy.getDestination()), copy);
                        }
                    } else if (n instanceof AbstractNewObjectNode || n instanceof CommitAllocationNode) {
                        allocates.add(name);
                    } else if (n instanceof Invoke invoke) {
                        // No flow, a disabled one or one without callees: the analysis
                        // found no target. Its reasons can be wrong (a field a native
                        // writes looks always null), so the call may touch anything.
                        InvokeTypeFlow flow = flows.get(invoke.bci());
                        String why = flow == null ? "no flow" : !flow.isFlowEnabled() ? "disabled" : flow.getOriginalCallees().isEmpty() ? "no callees" : null;
                        if (why != null) {
                            add(unresolved, name, GraphExport.methodKey(invoke.getTargetMethod()) + at + " (" + why + ")");
                        }
                    } else if (n instanceof FinalFieldBarrierNode && ptm.isConstructor()) {
                        // Ordered by the reference: the translation has a constructor
                        // return its receiver, and every later use take that.
                    } else if ((MemoryKill.isMemoryKill(n) || n instanceof MemoryAccess) && !isBookkeeping(n)) {
                        add(unknown, name, n.getClass().getSimpleName() + at);
                    }
                }
            }
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
            // one. 
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
        all.retainAll(program);

        out.println();
        out.println("=== local per-method field effects ===");
        if (all.isEmpty()) {
            out.println("  (nothing reported -- wrong -Ddump.filter, or no reachable");
            out.println("   field accesses in the analysed program?)");
        }
        for (String m : all) {
            out.printf("  %-34s reads=%-28s writes=%s%n",
                            m,
                            reads.getOrDefault(m, new TreeSet<>()),
                            writes.getOrDefault(m, new TreeSet<>()));
        }

        out.println();
        out.println("=== call graph with points-to resolved callees ===");
        for (String m : new TreeSet<>(callees.keySet())) {
            if (!program.contains(m)) {
                continue;
            }
            TreeSet<String> targets = new TreeSet<>();
            for (String t : callees.get(m)) {
                targets.add(isUnderAnalysis(t.substring(0, t.lastIndexOf('.', t.indexOf('(')))) ? t : "<platform>");
            }
            targets.remove("<platform>");
            if (!targets.isEmpty()) {
                out.printf("  %-34s -> %s%n", m, targets);
            }
        }

        out.println();
        out.println("=== reachable fields ===");
        TreeMap<String, boolean[]> fields = new TreeMap<>();
        for (AnalysisField f : universe.getFields()) {
            String owner = f.getDeclaringClass().toJavaName(true);
            if (!isUnderAnalysis(owner)) {
                continue;
            }
            fields.put(owner + "." + f.getName(), new boolean[]{f.isRead(), f.isWritten()});
        }
        for (var e : fields.entrySet()) {
            out.printf("  %-30s read=%-6s written=%s%n",
                            e.getKey(), e.getValue()[0], e.getValue()[1]);
        }

        out.println();
        out.println("=== memory effects the facts can't name, and calls without a target ===");
        for (String m : program) {
            for (String what : unknown.getOrDefault(m, new TreeSet<>())) {
                out.printf("  %-34s %s%n", m, what);
            }
            for (String what : unresolved.getOrDefault(m, new TreeSet<>())) {
                out.printf("  %-34s unresolved call to %s%n", m, what);
            }
        }

        String facts = factsJson(analysed, reads, writes, callees, allocates, unknown, unresolved, accesses, fields);
        if (!jsonPath.isEmpty()) {
            write(jsonPath, "{\n" + facts + "\n}\n");
            out.println();
            out.println("wrote " + jsonPath);
        }

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
            out.println();
            out.println("wrote " + graphs.size() + " graphs to " + irPath);
        }
    }

    private static String factsJson(Set<String> methods,
                    TreeMap<String, TreeSet<String>> reads,
                    TreeMap<String, TreeSet<String>> writes,
                    TreeMap<String, TreeSet<String>> callees,
                    Set<String> allocates,
                    TreeMap<String, TreeSet<String>> unknown,
                    TreeMap<String, TreeSet<String>> unresolved,
                    TreeMap<String, TreeSet<String>> accesses,
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
                            .append(", \"allocates\": ").append(allocates.contains(m))
                            .append(", \"unknown\": ").append(jsonArray(unknown.get(m)))
                            .append(", \"unresolved\": ").append(jsonArray(unresolved.get(m)));
            if (accesses.containsKey(m)) {
                sb.append(", \"accesses\": [").append(String.join(", ", accesses.get(m))).append("]");
            }
            sb.append("}");
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

    /**
     * Nodes that kill or read memory for Graal's bookkeeping only: the state at
     * the method's start and at a handler's, the creation of an exception on a
     * path that throws, and an array's length, which never changes.
     */
    private static boolean isBookkeeping(Node n) {
        return n instanceof StartNode || n instanceof ExceptionObjectNode || n instanceof BytecodeExceptionNode || n instanceof ArrayLengthNode;
    }

    private static void add(TreeMap<String, TreeSet<String>> facts, String method, String fact) {
        facts.computeIfAbsent(method, k -> new TreeSet<>()).add(fact);
    }

    /**
     * A field or array access, where it is, and the objects its receiver may point
     * to, null when the analysis can't say: {"kind": "read", "field": "Examples$Counter.value",
     * "receivers": ["Examples$Counter@Examples.main([Ljava/lang/String;)V:9"],
     * "at": "Examples.length(LExamples$Link;)I:5"}.
     */
    private static void addAccess(TreeMap<String, TreeSet<String>> accesses, String method, String kind, String field, List<String> receivers, Node node) {
        Map<String, Object> access = new java.util.LinkedHashMap<>();
        access.put("kind", kind);
        access.put("field", field);
        access.put("receivers", receivers);
        access.put("at", GraphExport.PointsTo.site(node instanceof ValueNode value ? value.getNodeSourcePosition() : null));
        add(accesses, method, GraphExport.toJson(access, 2));
    }

    /**
     * An array element's partition, by element kind. boolean[] and byte[]
     * share one, as they share baload and bastore, and every reference array
     * is Object[]: an Object[] may be a String[].
     */
    private static String arrayPartition(JavaKind kind) {
        return switch (kind) {
            case Boolean, Byte -> "byte[]";
            case Object -> "Object[]";
            default -> kind.getJavaName() + "[]";
        };
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
