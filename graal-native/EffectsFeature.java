import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

import org.graalvm.word.LocationIdentity;

import com.oracle.graal.pointsto.PointsToAnalysis;
import com.oracle.svm.core.feature.InternalFeature;
import com.oracle.svm.hosted.FeatureImpl;
import com.oracle.svm.hosted.meta.HostedField;
import com.oracle.svm.hosted.meta.HostedMethod;

import jdk.graal.compiler.graph.Node;
import jdk.graal.compiler.nodes.FieldLocationIdentity;
import jdk.graal.compiler.nodes.GraphState;
import jdk.graal.compiler.nodes.Invoke;
import jdk.graal.compiler.nodes.NamedLocationIdentity;
import jdk.graal.compiler.nodes.StructuredGraph;
import jdk.graal.compiler.nodes.cfg.ControlFlowGraph;
import jdk.graal.compiler.nodes.cfg.HIRBlock;
import jdk.graal.compiler.nodes.java.AccessFieldNode;
import jdk.graal.compiler.nodes.java.LoadFieldNode;
import jdk.graal.compiler.nodes.java.MethodCallTargetNode;
import jdk.graal.compiler.nodes.java.StoreFieldNode;
import jdk.graal.compiler.nodes.memory.AbstractWriteNode;
import jdk.graal.compiler.nodes.memory.FloatingReadNode;
import jdk.graal.compiler.nodes.memory.MemoryAccess;
import jdk.graal.compiler.nodes.memory.ReadNode;
import jdk.graal.compiler.phases.Phase;
import jdk.graal.compiler.phases.tiers.Suites;
import jdk.graal.compiler.phases.util.Providers;
import jdk.vm.ci.meta.JavaKind;
import jdk.vm.ci.meta.ResolvedJavaMethod;

/**
 * The round trip in one native-image build. After the analysis, the feature exports its facts
 * with graal-export's exporter and runs our tool on them (effects.kills), which says what each
 * method, with everything it calls, may write. Before Graal compiles, every call in the
 * program's methods kills only those locations instead of all of memory, and Graal's own
 * phases do the rest. A phase at the end of the low tier counts the field stores, field loads
 * and calls left in the program's methods.
 *
 * Configured with system properties, passed as -J-D...:
 * <ul>
 * <li>{@code effects.out}: the directory for the export, the kills and the counts;</li>
 * <li>{@code effects.program}: comma-separated class-name prefixes of the program, by default
 * every class outside the platform's packages, as graal-export has it;</li>
 * <li>{@code effects.tool}: the explicit-effects repository, whose tool runs with uv;</li>
 * <li>{@code effects.uv}: uv itself, as the builder's environment may not find it;</li>
 * <li>{@code effects.narrow}: {@code false} to only count, as Graal compiles by itself;</li>
 * <li>{@code effects.partition}: {@code object-field} to give each access to a field the location
 * of its partition of the objects, as points-to analysis splits them, and to have calls kill
 * partitions; {@code field}, the default, keeps Graal's locations;</li>
 * <li>{@code effects.lie}: a method whose kills to claim are none, so that a wrong answer shows
 * in the program's output;</li>
 * <li>{@code effects.split}: a method in which to claim that different references never meet,
 * as an unsound points-to analysis would, so that a wrong partition shows in the output;</li>
 * <li>{@code effects.decisions}: {@code true} to also remove the stores our rules find dead, in
 * Java (rules.decisions), before Graal compiles;</li>
 * <li>{@code effects.dead}: a position whose stores to claim are dead, the same for decisions.</li>
 * </ul>
 */
public final class EffectsFeature implements InternalFeature {

    private final Path out = Path.of(System.getProperty("effects.out", "effects"));
    private final List<String> program = List.of(System.getProperty("effects.program", "").split(","));
    private final boolean narrow = !System.getProperty("effects.narrow", "true").equals("false");
    private final String partition = System.getProperty("effects.partition", "field");
    private final boolean decisions = System.getProperty("effects.decisions", "false").equals("true");
    private final String label = System.getProperty("effects.label",
                    !narrow ? "graal" : decisions ? "decisions" : partition.equals("field") ? "kills" : "objects");

    /** Method name and descriptor -> the partitions it may write; absent: anything. */
    private final Map<String, List<String>> written = new HashMap<>();
    /** Where an access is, a tab, and its field -> its partition. */
    private final Map<String, String> located = new HashMap<>();
    /** Where a store our rules find dead is, a tab, and its field. */
    private final Set<String> dead = new HashSet<>();
    /** The image's fields by name, to give Graal's locations for the partitions. */
    private final Map<String, HostedField> fields = new HashMap<>();
    /** What the low tier leaves of each of the program's methods, and the calls narrowed in it. */
    private final Map<String, String> counts = new ConcurrentHashMap<>();
    private final Map<String, List<String>> narrowed = new ConcurrentHashMap<>();

    @Override
    public void afterAnalysis(AfterAnalysisAccess access) {
        if (!narrow) {
            return;
        }
        FeatureImpl.AfterAnalysisAccessImpl impl = (FeatureImpl.AfterAnalysisAccessImpl) access;
        Path export = out.resolve("export.json");
        Path answer = out.resolve("kills.txt");
        Path partitions = out.resolve("accesses.txt");
        try {
            Files.createDirectories(out);
            ReadWriteExport.export((PointsToAnalysis) impl.getBigBang(), impl.getUniverse(), "", export.toString(), null);
            List<String> command = new ArrayList<>(List.of(System.getProperty("effects.uv", "uv"), "run", "--project", System.getProperty("effects.tool", "."),
                            "python", "-m", "effects.kills", export.toString(), "-o", answer.toString(), "--partition", partition));
            if (!partition.equals("field")) {
                command.addAll(List.of("--accesses", partitions.toString()));
            }
            Process tool = new ProcessBuilder(command).inheritIO().start();
            if (tool.waitFor() != 0) {
                throw new IllegalStateException("effects.kills failed on " + export);
            }
            for (String line : Files.readAllLines(answer)) {
                String[] parts = line.split("\t", -1);
                if (!parts[1].equals("any")) {
                    written.put(parts[0], parts[1].isEmpty() ? List.of() : List.of(parts[1].split(",")));
                }
            }
            if (!partition.equals("field")) {
                for (String line : Files.readAllLines(partitions)) {
                    String[] parts = line.split("\t", -1);
                    located.put(parts[0] + "\t" + parts[1], parts[2]);
                }
            }
            if (decisions) {
                Path stores = out.resolve("dead.txt");
                Process rules = new ProcessBuilder(System.getProperty("effects.uv", "uv"), "run", "--project", System.getProperty("effects.tool", "."),
                                "python", "-m", "rules.decisions", export.toString(), "-o", stores.toString(), "--partition", partition).inheritIO().start();
                if (rules.waitFor() != 0) {
                    throw new IllegalStateException("rules.decisions failed on " + export);
                }
                dead.addAll(Files.readAllLines(stores));
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } catch (InterruptedException e) {
            throw new IllegalStateException(e);
        }
        String lie = System.getProperty("effects.lie", "");
        if (!lie.isEmpty()) {
            written.put(lie, List.of());
        }
    }

    @Override
    public void beforeCompilation(BeforeCompilationAccess access) {
        for (HostedField field : ((FeatureImpl.BeforeCompilationAccessImpl) access).getUniverse().getFields()) {
            fields.put(name(field), field);
        }
    }

    private static String name(jdk.vm.ci.meta.ResolvedJavaField field) {
        return field.getDeclaringClass().toJavaName(true) + "." + field.getName();
    }

    /**
     * Graal's locations for a partition the tool names: a field, an array kind, or with objects
     * told apart a field of a set of them, Aliasing$Counter.value@main:199. A field this graph
     * gives partitions is killed in its partition, and as a whole too, for the phases that key
     * field accesses by the field alone, such as read elimination; any other is killed whole.
     */
    private List<LocationIdentity> locations(String written, Set<String> partitioned) {
        String whole = written.contains("@") ? written.substring(0, written.indexOf('@')) : written;
        if (whole.endsWith("[]")) {
            return arrayKinds(whole).stream().map(NamedLocationIdentity::getArrayLocation).toList();
        }
        HostedField field = fields.get(whole);
        if (field == null) {
            return List.of(); // the image never accesses it, so there is nothing to kill
        }
        return partitioned.contains(whole) ? List.of(new FieldLocationIdentity(field), new FieldLocationIdentity(field, false, written))
                        : List.of(new FieldLocationIdentity(field));
    }

    /** The element kinds of an export's array partition: byte[] stands for boolean[] too. */
    private static List<JavaKind> arrayKinds(String partition) {
        return switch (partition) {
            case "byte[]" -> List.of(JavaKind.Byte, JavaKind.Boolean);
            case "Object[]" -> List.of(JavaKind.Object);
            default -> List.of(JavaKind.fromJavaClass(primitive(partition.substring(0, partition.length() - 2))));
        };
    }

    private static Class<?> primitive(String name) {
        return switch (name) {
            case "char" -> char.class;
            case "short" -> short.class;
            case "int" -> int.class;
            case "long" -> long.class;
            case "float" -> float.class;
            case "double" -> double.class;
            default -> throw new IllegalArgumentException("not an array kind: " + name);
        };
    }

    @Override
    public void registerGraalPhases(Providers providers, Suites suites, boolean hosted, boolean fallback) {
        if (hosted) {
            if (narrow) {
                suites.getHighTier().prependPhase(new NarrowKills());
            }
            if (!partition.equals("field")) {
                suites.getMidTier().prependPhase(new CheckPartitions());
            }
            suites.getLowTier().appendPhase(new CountAccesses());
        }
    }

    @Override
    public void afterCompilation(AfterCompilationAccess access) {
        StringBuilder text = new StringBuilder();
        for (Map.Entry<String, String> method : new TreeMap<>(counts).entrySet()) {
            text.append(method.getKey()).append('\n').append(String.format("    %-10s %s%n", label, method.getValue()));
            for (String call : narrowed.getOrDefault(method.getKey(), List.of())) {
                text.append("        ").append(call).append('\n');
            }
        }
        try {
            Files.createDirectories(out);
            Files.writeString(out.resolve("counts.txt"), text);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private boolean inProgram(ResolvedJavaMethod method) {
        String holder = method.getDeclaringClass().toJavaName(true);
        if (program.stream().allMatch(String::isEmpty)) {
            return ReadWriteExport.isUnderAnalysis(holder);
        }
        return program.stream().anyMatch(prefix -> !prefix.isEmpty() && holder.startsWith(prefix));
    }

    /** As the exporter names a method: Examples.length(LExamples$Link;)I. */
    private static String key(ResolvedJavaMethod method) {
        return method.getDeclaringClass().toJavaName(true) + "." + method.getName() + method.getSignature().toMethodDescriptor();
    }

    /** As graal-probe names a method: Examples.length(Link). */
    private static String probeName(ResolvedJavaMethod method) {
        String parameters = java.util.stream.IntStream.range(0, method.getSignature().getParameterCount(false))
                        .mapToObj(i -> simple(method.getSignature().getParameterType(i, null).toJavaName(true)))
                        .collect(Collectors.joining(", "));
        return method.getDeclaringClass().toJavaName(false) + "." + method.getName() + "(" + parameters + ")";
    }

    private static String simple(String name) {
        return name.substring(Math.max(name.lastIndexOf('.'), name.lastIndexOf('$')) + 1);
    }

    /** What a call may write: the kills of every method it may call, null for anything. */
    private LocationIdentity[] killsOf(MethodCallTargetNode target, Set<String> partitioned) {
        HostedMethod method = (HostedMethod) target.targetMethod();
        HostedMethod[] callees = target.invokeKind().isDirect() ? new HostedMethod[]{method} : method.getImplementations();
        if (callees.length == 0) {
            return null;
        }
        List<LocationIdentity> all = new ArrayList<>();
        for (HostedMethod callee : callees) {
            List<String> partitions = written.get(key(callee));
            if (partitions == null) {
                return null;
            }
            for (String partitionWritten : partitions) {
                all.addAll(locations(partitionWritten, partitioned));
            }
        }
        return all.toArray(new LocationIdentity[0]);
    }

    /** Removes the stores our rules find dead, and with effects.dead, the ones it claims are. */
    private void removeDeadStores(StructuredGraph graph, List<String> report) {
        String claimed = System.getProperty("effects.dead", "");
        if (dead.isEmpty() && claimed.isEmpty()) {
            return;
        }
        for (StoreFieldNode store : graph.getNodes().filter(StoreFieldNode.class).snapshot()) {
            String at = GraphExport.PointsTo.site(store.getNodeSourcePosition());
            if (at != null && (dead.contains(at + "\t" + name(store.field())) || at.equals(claimed))) {
                jdk.graal.compiler.nodes.util.GraphUtil.removeFixedWithUnusedInputs(store);
                report.add(String.format("dead store to %s at bci %d removed", simple(name(store.field()).substring(0, name(store.field()).lastIndexOf('.')))
                                + name(store.field()).substring(name(store.field()).lastIndexOf('.')), store.getNodeSourcePosition().getBCI()));
            }
        }
    }

    /** The reference an access goes through, for the split: a parameter, or any other value. */
    private static String reference(AccessFieldNode access) {
        return jdk.graal.compiler.nodes.util.GraphUtil.unproxify(access.object()) instanceof jdk.graal.compiler.nodes.ParameterNode parameter
                        ? "param" + parameter.index() : "v" + access.object().getId();
    }

    /**
     * Gives each access to a field the location of its partition, if every access to the field in
     * the graph has one and they aren't all of one partition; the others keep the field's. Returns
     * the fields given partitions.
     */
    private Set<String> partition(StructuredGraph graph, List<String> report) {
        boolean split = key(graph.method()).equals(System.getProperty("effects.split", ""));
        Map<String, List<AccessFieldNode>> byField = new TreeMap<>();
        for (AccessFieldNode access : graph.getNodes().filter(AccessFieldNode.class)) {
            byField.computeIfAbsent(name(access.field()), k -> new ArrayList<>()).add(access);
        }
        Set<String> partitioned = new HashSet<>();
        for (Map.Entry<String, List<AccessFieldNode>> field : byField.entrySet()) {
            List<String> partitions = new ArrayList<>();
            for (AccessFieldNode access : field.getValue()) {
                String at = GraphExport.PointsTo.site(access.getNodeSourcePosition());
                String found = at == null || access.getLocationIdentity().isImmutable() || access.ordersMemoryAccesses() ? null
                                : located.get(at + "\t" + field.getKey());
                partitions.add(found == null || !split ? found : found + "#" + reference(access));
            }
            if (partitions.contains(null) || partitions.stream().allMatch(field.getKey()::equals)) {
                continue;
            }
            for (int i = 0; i < partitions.size(); i++) {
                field.getValue().get(i).setLocationIdentity(new FieldLocationIdentity(field.getValue().get(i).field(), false, partitions.get(i)));
            }
            partitioned.add(field.getKey());
            report.add(String.format("%s in %s", simple(field.getKey().substring(0, field.getKey().lastIndexOf('.'))) + field.getKey().substring(field.getKey().lastIndexOf('.')),
                            new java.util.TreeSet<>(partitions).stream().map(p -> p.contains("@") ? p.substring(p.indexOf('@')) : p).collect(Collectors.joining(" "))));
        }
        return partitioned;
    }

    /** Narrows each call in the program's methods to what its callees may write. */
    private final class NarrowKills extends Phase {
        @Override
        public Optional<NotApplicable> notApplicableTo(GraphState graphState) {
            return ALWAYS_APPLICABLE;
        }

        @Override
        protected void run(StructuredGraph graph) {
            if (!inProgram(graph.method())) {
                return;
            }
            List<String> calls = new ArrayList<>();
            removeDeadStores(graph, calls);
            Set<String> partitioned = located.isEmpty() ? Set.of() : partition(graph, calls);
            for (Node node : graph.getNodes()) {
                if (node instanceof Invoke invoke && invoke.callTarget() instanceof MethodCallTargetNode target) {
                    LocationIdentity[] locations = killsOf(target, partitioned);
                    if (locations != null) {
                        invoke.setKilledLocationIdentities(locations);
                        LocationIdentity[] set = Invoke.killSet(locations);
                        calls.add(String.format("%s kills %s", probeName(target.targetMethod()), set.length == 0 ? "nothing"
                                        : java.util.Arrays.stream(set).map(l -> simple(l.toString())).collect(Collectors.joining(" "))));
                    }
                }
            }
            if (!calls.isEmpty()) {
                Collections.sort(calls);
                narrowed.put(probeName(graph.method()), calls);
            }
        }
    }

    /**
     * Stops the build if a graph has accesses to one field both with and without a partition, as
     * a phase that makes a new access after the partitioning could: their locations would not
     * overlap, and nothing would order them.
     */
    private final class CheckPartitions extends Phase {
        @Override
        public Optional<NotApplicable> notApplicableTo(GraphState graphState) {
            return ALWAYS_APPLICABLE;
        }

        @Override
        protected void run(StructuredGraph graph) {
            Map<jdk.vm.ci.meta.ResolvedJavaField, Set<Boolean>> kinds = new HashMap<>();
            for (Node node : graph.getNodes()) {
                if (node instanceof MemoryAccess access && access.getLocationIdentity() instanceof FieldLocationIdentity field && !field.isImmutable()) {
                    kinds.computeIfAbsent(field.getField(), k -> new HashSet<>()).add(field.getPartition() != null);
                }
            }
            kinds.forEach((field, partitioned) -> {
                if (partitioned.size() > 1) {
                    throw new IllegalStateException(graph.method().format("%H.%n") + " accesses " + name(field) + " both with and without a partition");
                }
            });
        }
    }

    private final class CountAccesses extends Phase {
        @Override
        public Optional<NotApplicable> notApplicableTo(GraphState graphState) {
            return ALWAYS_APPLICABLE;
        }

        @Override
        protected void run(StructuredGraph graph) {
            if (!inProgram(graph.method())) {
                return;
            }
            ControlFlowGraph cfg = ControlFlowGraph.newBuilder(graph).connectBlocks(true).computeLoops(true).build();
            Map<String, Integer> writes = new TreeMap<>();
            Map<String, Integer> reads = new TreeMap<>();
            int calls = 0;
            for (Node node : graph.getNodes()) {
                if (node instanceof Invoke) {
                    calls++;
                } else if (node instanceof MemoryAccess access && access.getLocationIdentity() instanceof FieldLocationIdentity field) {
                    HIRBlock block = cfg.blockFor(node);
                    boolean loop = block != null && block.getLoop() != null;
                    String where = simple(field.getField().format("%H")) + "." + field.getField().getName() + (loop ? "(loop)" : "");
                    Map<String, Integer> counted = node instanceof StoreFieldNode || node instanceof AbstractWriteNode ? writes
                                    : node instanceof LoadFieldNode || node instanceof ReadNode || node instanceof FloatingReadNode ? reads : null;
                    if (counted != null) {
                        counted.merge(where, 1, Integer::sum);
                    }
                }
            }
            counts.put(probeName(graph.method()), String.format("calls %d   writes %-32s reads %s", calls, show(writes), show(reads)));
        }

        private static String show(Map<String, Integer> counted) {
            return counted.isEmpty() ? "-"
                            : counted.entrySet().stream().map(e -> e.getKey() + (e.getValue() > 1 ? "×" + e.getValue() : "")).collect(Collectors.joining(" "));
        }
    }
}
