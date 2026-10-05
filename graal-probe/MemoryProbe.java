package probe;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.stream.Collectors;

import org.graalvm.word.LocationIdentity;
import org.junit.Assume;
import org.junit.Test;

import jdk.graal.compiler.core.phases.HighTier;
import jdk.graal.compiler.core.test.GraalCompilerTest;
import jdk.graal.compiler.graph.Node;
import jdk.graal.compiler.java.BytecodeParserOptions;
import jdk.graal.compiler.nodeinfo.Verbosity;
import jdk.graal.compiler.nodes.FieldLocationIdentity;
import jdk.graal.compiler.nodes.FixedWithNextNode;
import jdk.graal.compiler.nodes.GraphState;
import jdk.graal.compiler.nodes.Invoke;
import jdk.graal.compiler.nodes.StructuredGraph;
import jdk.graal.compiler.nodes.StructuredGraph.AllowAssumptions;
import jdk.graal.compiler.nodes.cfg.ControlFlowGraph;
import jdk.graal.compiler.nodes.cfg.HIRBlock;
import jdk.graal.compiler.nodes.java.LoadFieldNode;
import jdk.graal.compiler.nodes.java.StoreFieldNode;
import jdk.graal.compiler.nodes.memory.AbstractWriteNode;
import jdk.graal.compiler.nodes.memory.FixedAccessNode;
import jdk.graal.compiler.nodes.memory.FloatingReadNode;
import jdk.graal.compiler.nodes.memory.MemoryAccess;
import jdk.graal.compiler.nodes.memory.ReadNode;
import jdk.graal.compiler.options.OptionValues;
import jdk.graal.compiler.phases.BasePhase;
import jdk.graal.compiler.phases.PhaseSuite;
import jdk.graal.compiler.phases.tiers.Suites;
import jdk.vm.ci.meta.ResolvedJavaMethod;

/**
 * Utility to assess whether Graal optimizes away memory accesses.
 *
 * Each static method of the example classes is compiled with the real suite twice:
 * inlining as Graal decides, and with no inlining at all, so that calls stay calls.
 * The field stores, field loads and calls of the method's own bytecode are set
 * against what is left. 
 *
 */
public class MemoryProbe extends GraalCompilerTest {

    private static List<Class<?>> examples() {
        List<Class<?>> classes = new ArrayList<>();
        for (String name : System.getProperty("probe.examples", "Examples").split(",")) {
            classes.add(example(name.trim()));
        }
        return classes;
    }

    /**
     * Loads an example and every class it declares, so that class hierarchy
     * analysis sees all the implementations of an interface and cannot
     * devirtualize a call the example means to keep virtual.
     */
    private static Class<?> example(String name) {
        try {
            Class<?> example = Class.forName(name);
            for (Class<?> member : example.getDeclaredClasses()) {
                Class.forName(member.getName(), true, example.getClassLoader());
            }
            return example;
        } catch (ClassNotFoundException e) {
            throw new AssertionError("no example class " + name, e);
        }
    }

    /** The example's own static methods, except main. */
    private static List<Method> methods(Class<?> example) {
        return Arrays.stream(example.getDeclaredMethods())
                        .filter(m -> Modifier.isStatic(m.getModifiers()) && !m.isSynthetic() && !m.getName().equals("main"))
                        .sorted(Comparator.comparing(Method::getName).thenComparing(Method::getParameterCount))
                        .collect(Collectors.toList());
    }

    /**
     * No inlining at all: neither the inlining phase nor the parser, which on
     * its own inlines methods of up to TrivialInliningSize bytes of bytecode.
     */
    private OptionValues noInlining() {
        return new OptionValues(getInitialOptions(), HighTier.Options.Inline, false, BytecodeParserOptions.InlineDuringParsing, false);
    }

    // --- counting ---------------------------------------------------------

    /** The field stores, field loads and calls in a graph, by location. */
    private record Memory(Map<String, Integer> writes, Map<String, Integer> reads, int calls) {

        static Memory of(StructuredGraph graph) {
            ControlFlowGraph cfg = ControlFlowGraph.newBuilder(graph).connectBlocks(true).computeLoops(true).build();
            Map<String, Integer> writes = new TreeMap<>();
            Map<String, Integer> reads = new TreeMap<>();
            int calls = 0;
            for (Node n : graph.getNodes()) {
                if (n instanceof Invoke) {
                    calls++;
                } else if (n instanceof MemoryAccess access && access.getLocationIdentity() instanceof FieldLocationIdentity field) {
                    String where = shorten(field) + (inLoop(cfg, n) ? "(loop)" : "");
                    if (n instanceof StoreFieldNode || n instanceof AbstractWriteNode) {
                        writes.merge(where, 1, Integer::sum);
                    } else if (n instanceof LoadFieldNode || n instanceof ReadNode || n instanceof FloatingReadNode) {
                        reads.merge(where, 1, Integer::sum);
                    }
                }
            }
            return new Memory(writes, reads, calls);
        }

        /** Whether a fixed access is in a loop. A floating one has no block yet, so it is not. */
        private static boolean inLoop(ControlFlowGraph cfg, Node n) {
            HIRBlock block = cfg.blockFor(n);
            return block != null && block.getLoop() != null;
        }

        @Override
        public String toString() {
            return String.format("calls %d   writes %-32s reads %s", calls, show(writes), show(reads));
        }

        private static String show(Map<String, Integer> counts) {
            if (counts.isEmpty()) {
                return "-";
            }
            return counts.entrySet().stream()
                            .map(e -> e.getKey() + (e.getValue() > 1 ? "×" + e.getValue() : ""))
                            .collect(Collectors.joining(" "));
        }
    }

    /** Examples$Counter.value -> Counter.value */
    private static String shorten(LocationIdentity location) {
        String id = location.toString();
        return id.substring(id.lastIndexOf('$') + 1);
    }

    @Test
    public void whatGraalLeaves() {
        System.out.println();
        System.out.println("=== field stores, field loads and calls: in the bytecode, and left after the full suite ===");
        for (Class<?> example : examples()) {
            for (Method method : methods(example)) {
                ResolvedJavaMethod m = getMetaAccess().lookupJavaMethod(method);
                String parameters = Arrays.stream(method.getParameterTypes()).map(Class::getSimpleName).collect(Collectors.joining(", "));
                System.out.printf("%s.%s(%s)%n", example.getSimpleName(), method.getName(), parameters);
                System.out.printf("    %-10s %s%n", "bytecode", Memory.of(parseEager(m, AllowAssumptions.NO, noInlining())));
                System.out.printf("    %-10s %s%n", "inlining", Memory.of(getFinalGraph(m)));
                System.out.printf("    %-10s %s%n", "no inline", Memory.of(getFinalGraph(m, noInlining())));
            }
        }
        System.out.println();
    }

    // Interleave a recording phase after every phase of the real suite and
    // print only the phases after which the counts change.
    private static boolean tracing;
    private static boolean dumpingChain;
    private static final List<String> trace = new ArrayList<>();

    /** A no-op phase that records the counts at its position in the suite. */
    static final class Record extends BasePhase<Object> {
        private final String label;

        Record(String label) {
            this.label = label;
        }

        @Override
        public Optional<NotApplicable> notApplicableTo(GraphState graphState) {
            return ALWAYS_APPLICABLE;
        }

        @Override
        public boolean checkContract() {
            return false;
        }

        @Override
        protected void run(StructuredGraph graph, Object context) {
            trace.add(label + "|" + Memory.of(graph));
        }
    }

    @Override
    protected Suites createSuites(OptionValues opts) {
        Suites suites = super.createSuites(opts);
        if (tracing) {
            interleave(suites.getHighTier(), "high");
            interleave(suites.getMidTier(), "mid ");
            interleave(suites.getLowTier(), "low ");
        }
        if (dumpingChain) {
            surround(suites.getMidTier(), "FloatingReadPhase");
        }
        return suites;
    }

    private static <C> void interleave(PhaseSuite<C> suite, String tier) {
        List<String> names = new ArrayList<>();
        for (BasePhase<? super C> phase : suite.getPhases()) {
            names.add(phase.getClass().getSimpleName());
        }
        for (int i = names.size() - 1; i >= 0; i--) {
            suite.insertAtIndex(i + 1, new Record(tier + " after " + names.get(i)));
        }
        suite.insertAtIndex(0, new Record(tier + " (entry)"));
    }

    /** Compiles one Examples method with the suite instrumented, collecting the trace. */
    private void compileTraced(String method, OptionValues options) {
        trace.clear();
        Class<?> examples = examplesClass();
        ResolvedJavaMethod m = getResolvedJavaMethod(examples, method);
        if (options == null) {
            getFinalGraph(m);
        } else {
            getFinalGraph(m, options);
        }
    }

    /** The deep dives use Examples; skipped when it is not among the examples. */
    private static Class<?> examplesClass() {
        Assume.assumeTrue(System.getProperty("probe.examples", "Examples").contains("Examples"));
        return example("Examples");
    }

    private void traceMethod(String method, OptionValues options, String note) {
        tracing = true;
        try {
            compileTraced(method, options);
        } finally {
            tracing = false;
        }
        System.out.println("--- " + method + note);
        String previous = null;
        for (String line : trace) {
            int bar = line.indexOf('|');
            String state = line.substring(bar + 1);
            if (!state.equals(previous)) {
                System.out.printf("    %-42s %s%n", line.substring(0, bar), state);
                previous = state;
            }
        }
    }

    @Test
    public void whichPhase() {
        examplesClass();
        System.out.println();
        System.out.println("=== where the counts change, phase by phase ===");
        traceMethod("deadStoreOtherField", null, "");
        traceMethod("deadStoreBothArms", null, "");
        traceMethod("deadStoreOneArm", null, "");
        traceMethod("forwardAcrossCall", null, "");
        traceMethod("forwardAcrossCall", noInlining(), "  [no inlining]");
        traceMethod("forwardAcrossWritingCall", null, "");
        traceMethod("forwardAcrossVirtualCall", null, "");
        traceMethod("hoistLoadOutOfLoop", null, "");
        System.out.println();
    }

    // --- the memory graph around FloatingReadPhase ------------------------
    //
    // WriteNode.simplify removes a store only when next() is the write that
    // overwrites it. Dump the memory accesses either side of FloatingReadPhase,
    // which builds the lastLocationAccess edges and floats the reads.

    static final class DumpChain extends BasePhase<Object> {
        private final String label;

        DumpChain(String label) {
            this.label = label;
        }

        @Override
        public Optional<NotApplicable> notApplicableTo(GraphState graphState) {
            return ALWAYS_APPLICABLE;
        }

        @Override
        public boolean checkContract() {
            return false;
        }

        @Override
        protected void run(StructuredGraph graph, Object context) {
            trace.add("    " + label);
            for (Node n : graph.getNodes()) {
                if ((n instanceof FixedAccessNode || n instanceof FloatingReadNode) && n instanceof MemoryAccess access) {
                    trace.add(String.format("      %-12s loc=%-16s usages=%d  next=%-14s lastLocationAccess=%s",
                                    brief(n), shorten(access.getLocationIdentity()), n.getUsageCount(),
                                    n instanceof FixedWithNextNode fixed ? brief(fixed.next()) : "-",
                                    access.getLastLocationAccess() == null ? "null" : brief(access.getLastLocationAccess().asNode())));
                }
            }
        }
    }

    /** Inserts a dump immediately before and immediately after a named phase. */
    private static <C> void surround(PhaseSuite<C> suite, String phaseName) {
        List<BasePhase<? super C>> phases = suite.getPhases();
        for (int i = 0; i < phases.size(); i++) {
            if (phases.get(i).getClass().getSimpleName().equals(phaseName)) {
                suite.insertAtIndex(i + 1, new DumpChain("after " + phaseName));
                suite.insertAtIndex(i, new DumpChain("before " + phaseName));
                return;
            }
        }
        throw new AssertionError("no phase named " + phaseName + " in " + suite);
    }

    private static String brief(Node n) {
        return n == null ? "-" : n.toString(Verbosity.Short);
    }

    private void chainDump(String method, OptionValues options, String note) {
        dumpingChain = true;
        try {
            compileTraced(method, options);
        } finally {
            dumpingChain = false;
        }
        System.out.println("--- " + method + note);
        trace.forEach(System.out::println);
    }

    @Test
    public void memoryChain() {
        examplesClass();
        System.out.println();
        System.out.println("=== memory accesses either side of FloatingReadPhase ===");
        chainDump("deadStoreOtherField", null, "");
        chainDump("deadStoreBothArms", null, "");
        chainDump("forwardAcrossCall", noInlining(), "  [no inlining]");
        chainDump("forwardAcrossVirtualCall", null, "");
        System.out.println();
    }
}
