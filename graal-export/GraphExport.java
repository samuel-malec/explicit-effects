import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.oracle.graal.pointsto.PointsToAnalysis;
import com.oracle.graal.pointsto.flow.AnalysisParsedGraph;
import com.oracle.graal.pointsto.flow.CallSiteSensitiveMethodTypeFlow;
import com.oracle.graal.pointsto.flow.ConstantTypeFlow;
import com.oracle.graal.pointsto.flow.InvokeTypeFlow;
import com.oracle.graal.pointsto.flow.LoadFieldTypeFlow;
import com.oracle.graal.pointsto.flow.MethodFlowsGraph;
import com.oracle.graal.pointsto.flow.MethodTypeFlowBuilder;
import com.oracle.graal.pointsto.flow.NewInstanceTypeFlow;
import com.oracle.graal.pointsto.flow.OffsetLoadTypeFlow.LoadIndexedTypeFlow;
import com.oracle.graal.pointsto.flow.TypeFlow;
import com.oracle.graal.pointsto.flow.context.object.AllocationContextSensitiveObject;
import com.oracle.graal.pointsto.flow.context.object.AnalysisObject;
import com.oracle.graal.pointsto.flow.context.object.ConstantContextSensitiveObject;
import com.oracle.graal.pointsto.heap.ImageHeapConstant;
import com.oracle.graal.pointsto.meta.AnalysisMethod;
import com.oracle.graal.pointsto.meta.AnalysisType;
import com.oracle.graal.pointsto.meta.PointsToAnalysisMethod;
import com.oracle.graal.pointsto.phases.InlineBeforeAnalysis;
import com.oracle.graal.pointsto.typestate.TypeState;

import jdk.graal.compiler.bytecode.BytecodeStream;
import jdk.graal.compiler.bytecode.Bytecodes;
import jdk.graal.compiler.core.common.type.AbstractObjectStamp;
import jdk.graal.compiler.core.common.type.FloatStamp;
import jdk.graal.compiler.core.common.type.IntegerStamp;
import jdk.graal.compiler.core.common.type.Stamp;
import jdk.graal.compiler.debug.DebugContext;
import jdk.graal.compiler.graph.Node;
import jdk.graal.compiler.graph.NodeSourcePosition;
import jdk.graal.compiler.graph.Position;
import jdk.graal.compiler.nodeinfo.InputType;
import jdk.graal.compiler.nodes.AbstractBeginNode;
import jdk.graal.compiler.nodes.AbstractDeoptimizeNode;
import jdk.graal.compiler.nodes.AbstractEndNode;
import jdk.graal.compiler.nodes.AbstractFixedGuardNode;
import jdk.graal.compiler.nodes.AbstractMergeNode;
import jdk.graal.compiler.nodes.ConstantNode;
import jdk.graal.compiler.nodes.LogicNode;
import jdk.graal.compiler.nodes.LoopExitNode;
import jdk.graal.compiler.nodes.NodeView;
import jdk.graal.compiler.nodes.PhiNode;
import jdk.graal.compiler.nodes.ProxyNode;
import jdk.graal.compiler.nodes.VirtualState;
import jdk.graal.compiler.nodes.ControlSinkNode;
import jdk.graal.compiler.nodes.ControlSplitNode;
import jdk.graal.compiler.nodes.FixedNode;
import jdk.graal.compiler.nodes.IfNode;
import jdk.graal.compiler.nodes.Invoke;
import jdk.graal.compiler.nodes.InvokeWithExceptionNode;
import jdk.graal.compiler.nodes.ParameterNode;
import jdk.graal.compiler.nodes.ReturnNode;
import jdk.graal.compiler.nodes.StructuredGraph;
import jdk.graal.compiler.nodes.UnwindNode;
import jdk.graal.compiler.nodes.ValueNode;
import jdk.graal.compiler.nodes.ValuePhiNode;
import jdk.graal.compiler.nodes.WithExceptionNode;
import jdk.graal.compiler.nodes.cfg.ControlFlowGraph;
import jdk.graal.compiler.nodes.cfg.HIRBlock;
import jdk.graal.compiler.nodes.extended.AbstractBoxingNode;
import jdk.graal.compiler.nodes.extended.BytecodeExceptionNode;
import jdk.graal.compiler.nodes.extended.MembarNode;
import jdk.graal.compiler.nodes.extended.ValueAnchorNode;
import jdk.graal.compiler.nodes.java.AbstractNewObjectNode;
import jdk.graal.compiler.nodes.java.AccessFieldNode;
import jdk.graal.compiler.nodes.java.AccessIndexedNode;
import jdk.graal.compiler.nodes.java.ArrayLengthNode;
import jdk.graal.compiler.nodes.java.ExceptionObjectNode;
import jdk.graal.compiler.nodes.java.FinalFieldBarrierNode;
import jdk.graal.compiler.nodes.java.LoadFieldNode;
import jdk.graal.compiler.nodes.java.LoadIndexedNode;
import jdk.graal.compiler.nodes.java.MethodCallTargetNode;
import jdk.graal.compiler.nodes.java.NewInstanceNode;
import jdk.graal.compiler.nodes.java.StoreFieldNode;
import jdk.graal.compiler.nodes.util.GraphUtil;
import jdk.graal.compiler.phases.schedule.SchedulePhase;
import jdk.graal.compiler.nodes.java.InstanceOfNode;
import jdk.graal.compiler.nodes.java.NewArrayNode;
import jdk.graal.compiler.nodes.virtual.AllocatedObjectNode;
import jdk.graal.compiler.nodes.virtual.CommitAllocationNode;
import jdk.graal.compiler.nodes.virtual.VirtualArrayNode;
import jdk.graal.compiler.nodes.virtual.VirtualInstanceNode;
import jdk.vm.ci.meta.JavaKind;
import jdk.vm.ci.code.BytecodePosition;
import jdk.vm.ci.meta.JavaConstant;
import jdk.vm.ci.meta.JavaField;
import jdk.vm.ci.meta.ResolvedJavaField;
import jdk.vm.ci.meta.ResolvedJavaMethod;
import jdk.vm.ci.meta.ResolvedJavaType;

/**
 * Exports a method's Graal IR annotated with points-to analysis information
 */
final class GraphExport {

    private GraphExport() {
    }

    static Map<String, Object> export(PointsToAnalysis bb, PointsToAnalysisMethod method, ObjectNames objectNames) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", methodName(method));
        out.put("descriptor", stable(method.getSignature().toMethodDescriptor()));
        out.put("static", method.isStatic());
        List<String> unsupported = new ArrayList<>();
        out.put("unsupported", unsupported);

        StructuredGraph graph;
        try {
            graph = analysisGraph(bb, method);
        } catch (VirtualMachineError e) {
            throw e;
        } catch (Throwable t) {
            unsupported.add("no graph after the analysis (" + t.getClass().getSimpleName() + ")");
            return out;
        }
        if (graph == null) {
            unsupported.add("no graph");
            return out;
        }

        SchedulePhase.runWithoutContextOptimizations(graph, SchedulePhase.SchedulingStrategy.LATEST_OUT_OF_LOOPS, true);
        StructuredGraph.ScheduleResult schedule = graph.getLastSchedule();
        ControlFlowGraph cfg = schedule.getCFG();

        // The graph exactly as it is exported, with its schedule: with -H:Dump=:1 and a
        // -H:MethodFilter naming the method, IGV shows it as "Exported to JSON".
        DebugContext debug = graph.getDebug();
        try (DebugContext.Scope s = debug.scope("GraphExport", graph)) {
            debug.dump(DebugContext.BASIC_LEVEL, graph, "Exported to JSON");
        } catch (Throwable e) {
            throw debug.handle(e);
        }

        Map<String, List<InvokeTypeFlow>> flowsByBci = flows(method);

        PointsTo pointsTo = new PointsTo(bb, method);
        Map<String, String> values = new TreeMap<>();
        List<Object> blocks = new ArrayList<>();
        for (HIRBlock block : cfg.reversePostOrder()) {
            blocks.add(exportBlock(block, schedule, flowsByBci, pointsTo, objectNames, values, unsupported));
        }
        out.put("entry", cfg.getStartBlock().getId());
        out.put("blocks", blocks);
        out.put("values", values);
        return out;
    }

    /** A hidden class's address in its name, Foo$$Lambda/0x00000000a455d0c8, or .0x… in a descriptor. */
    private static final Pattern HIDDEN_ADDRESS = Pattern.compile("(?<=[./])0x[0-9a-f]{8,16}");

    /** Each hidden class's address, and what the export names it instead. */
    private static final Map<String, String> HIDDEN = new ConcurrentHashMap<>();

    /**
     * Gives each hidden class a name that is the same in every run. The JVM names a lambda's class,
     * or a method handle form's, after its address, Foo$$Lambda/0x00000000a455d0c8, which differs
     * in every run; Native Image renames them itself, the standalone analyzer doesn't. The address
     * becomes a hash of what the class is: its interfaces, and each method's name, signature,
     * bytecode, and the methods it invokes, which is what LambdaUtils.getSignature hashes for
     * lambdas. Classes the same in all of that, such as two string concatenations of one shape,
     * share the name: what they do to memory is the same, and their facts are merged.
     */
    static void nameHiddenClasses(Collection<AnalysisType> types, PrintStream report) {
        HIDDEN.clear();
        Map<String, Integer> named = new HashMap<>(); // a name → how many classes it names
        for (AnalysisType type : types) {
            Matcher address = HIDDEN_ADDRESS.matcher(type.toJavaName(true));
            if (address.find()) {
                String hash = contentHash(type.getWrapped());
                HIDDEN.put(address.group(), hash);
                named.merge(type.toJavaName(true).substring(0, address.start()) + hash, 1, Integer::sum);
            }
        }
        long shared = named.values().stream().filter(n -> n > 1).count();
        report.println(HIDDEN.size() + " hidden classes named by their code" + (shared == 0 ? ""
                        : ", " + shared + " names shared by classes with the same code"));
    }

    /** A name as the JVM gives it, with each hidden class's address replaced: see {@link #nameHiddenClasses}. */
    static String stable(String name) {
        if (HIDDEN.isEmpty() || !name.contains("0x")) {
            return name;
        }
        Matcher address = HIDDEN_ADDRESS.matcher(name);
        StringBuilder named = new StringBuilder();
        while (address.find()) {
            address.appendReplacement(named, Matcher.quoteReplacement(HIDDEN.getOrDefault(address.group(), address.group())));
        }
        return address.appendTail(named).toString();
    }

    /** What a class is, as 16 hex digits: see {@link #nameHiddenClasses}. */
    private static String contentHash(ResolvedJavaType type) {
        StringBuilder what = new StringBuilder();
        for (ResolvedJavaType i : type.getInterfaces()) {
            what.append(i.toJavaName(true)).append(';');
        }
        List<ResolvedJavaMethod> methods = new ArrayList<>();
        try {
            methods.addAll(List.of(type.getDeclaredMethods(false)));
            methods.addAll(List.of(type.getDeclaredConstructors(false)));
        } catch (RuntimeException | LinkageError e) { // named by its interfaces alone, the same in every run
            what.append("\nmethods unreadable: ").append(e.getClass().getName());
        }
        methods.sort(Comparator.comparing(m -> m.getName() + m.getSignature().toMethodDescriptor()));
        for (ResolvedJavaMethod method : methods) {
            what.append('\n').append(method.getName()).append(method.getSignature().toMethodDescriptor());
            byte[] code = method.getCode();
            if (code == null) {
                continue;
            }
            what.append(' ').append(HexFormat.of().formatHex(code));
            for (BytecodeStream stream = new BytecodeStream(code); stream.currentBCI() < stream.endBCI(); stream.next()) {
                int opcode = stream.currentBC();
                if (opcode == Bytecodes.INVOKEVIRTUAL || opcode == Bytecodes.INVOKESPECIAL || opcode == Bytecodes.INVOKESTATIC
                                || opcode == Bytecodes.INVOKEINTERFACE || opcode == Bytecodes.INVOKEDYNAMIC) {
                    int cpi = opcode == Bytecodes.INVOKEDYNAMIC ? stream.readCPI4() : stream.readCPI();
                    what.append(' ').append(method.getConstantPool().lookupMethod(cpi, opcode, method).format("%H.%n(%P)%R"));
                }
            }
        }
        // A hidden class another one names doesn't make it differ from run to run.
        String text = HIDDEN_ADDRESS.matcher(what).replaceAll("hidden");
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))).substring(0, 16);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * Names for the object constants of one export, the same in every run: the image heap numbers
     * its objects in whatever order the analysis's threads reach them, and the host VM prints an
     * object by its identity hash code. A string goes by its first characters, "value is null"; a
     * class by its name, java.lang.Integer.class; an object read from a static final field by the
     * field, limits.Synchronized.LOCK; any other by its type and a number, java.lang.Object#1.
     * Methods are exported in the order of their names, so the numbers count a type's objects in
     * the order the export meets them; an object keeps its first name in every graph, and two
     * objects that would share one get different numbers.
     */
    static final class ObjectNames {
        /** How many characters of a string its name shows. */
        private static final int SHOWN = 40;

        private final PointsToAnalysis bb;
        private final Map<JavaConstant, String> names = new HashMap<>();
        private final Set<String> taken = new HashSet<>();

        ObjectNames(PointsToAnalysis bb) {
            this.bb = bb;
        }

        /** The name of the object a constant node holds. */
        String name(ConstantNode node, JavaConstant object) {
            return names.computeIfAbsent(object, o -> {
                String known = known(node, o);
                return known != null ? free(known, false) : free(typeName(bb.getMetaAccess().lookupJavaType(o)), true);
            });
        }

        /** What a string, a class or the value of a static final field is known by; null for any other object. */
        private String known(ConstantNode node, JavaConstant object) {
            if (object instanceof ImageHeapConstant heap && heap.isBackedByHostedObject() && heap.getType().getJavaClass() == String.class) {
                String text = heap.toValueString();
                if (text.codePointCount(0, text.length()) > SHOWN) {
                    text = text.substring(0, text.offsetByCodePoints(0, SHOWN)) + "...";
                }
                StringBuilder name = new StringBuilder();
                quote(name, text); // as JSON writes it: on one line, with its quotes and backslashes escaped
                return name.toString();
            }
            ResolvedJavaType type = bb.getConstantReflectionProvider().asJavaType(object);
            if (type != null) {
                return typeName(type) + ".class";
            }
            ResolvedJavaField field = staticFinalRead(node);
            return field == null ? null : fieldName(field);
        }

        /** The name if no object has it yet, else the name with the first number no object has. */
        private String free(String name, boolean numbered) {
            if (!numbered && taken.add(name)) {
                return name;
            }
            for (int i = numbered ? 1 : 2;; i++) {
                if (taken.add(name + "#" + i)) {
                    return name + "#" + i;
                }
            }
        }

        /**
         * The static final field a constant was read from: the analysis folds a getstatic of one
         * into the field's value, which keeps the getstatic's position. Not
         * ImageHeapConstant.getOrigin(): of the fields that hold the object, that is whichever the
         * analysis happened to read first.
         */
        private static ResolvedJavaField staticFinalRead(ConstantNode node) {
            NodeSourcePosition position = node.getNodeSourcePosition();
            byte[] code = position == null ? null : position.getMethod().getCode();
            if (code == null || position.getBCI() < 0 || position.getBCI() >= code.length) {
                return null;
            }
            BytecodeStream stream = new BytecodeStream(code);
            stream.setBCI(position.getBCI());
            if (stream.currentBC() != Bytecodes.GETSTATIC) {
                return null;
            }
            JavaField field = position.getMethod().getConstantPool().lookupField(stream.readCPI(), position.getMethod(), Bytecodes.GETSTATIC);
            return field instanceof ResolvedJavaField resolved && resolved.isStatic() && resolved.isFinal() ? resolved : null;
        }
    }

    /** The graph the analysis built the method's flows from, null for a method without a body. */
    static StructuredGraph analysisGraph(PointsToAnalysis bb, PointsToAnalysisMethod method) {
        AnalysisParsedGraph parsed = method.ensureGraphParsed(bb);
        if (parsed.getEncodedGraph() == null) {
            return null;
        }
        StructuredGraph graph = InlineBeforeAnalysis.decodeGraph(bb, method, parsed);
        try (DebugContext.Scope s = graph.getDebug().scope("GraphExport", graph)) {
            MethodTypeFlowBuilder.optimizeGraphBeforeAnalysis(bb, method, graph);
        } catch (Throwable e) {
            throw graph.getDebug().handle(e);
        }
        return graph;
    }

    /**
     * The objects a reference may point to, as the points-to analysis names
     * them. A parameter, an object load, an invoke's result, an allocation
     * and a constant have a flow; a phi takes its inputs' objects, and a pi
     * or a proxy its input's. Null when the flows can't say, for a saturated
     * flow or a value without one: an access through it may then touch any
     * object with the field.
     *
     * With a context-sensitive analysis each context has a clone of the
     * method's flows, and a reference may point to what it does in any of them.
     */
    static final class PointsTo {
        private final PointsToAnalysis bb;
        private final PointsToAnalysisMethod method;
        private final MethodFlowsGraph flows;
        private final Map<BytecodePosition, List<TypeFlow<?>>> bySource = new HashMap<>();

        PointsTo(PointsToAnalysis bb, PointsToAnalysisMethod method) {
            this.bb = bb;
            this.method = method;
            this.flows = method.getTypeFlow().getMethodFlowsGraph();
            for (TypeFlow<?> flow : flows.flows()) {
                if (flow.getSource() instanceof BytecodePosition position) {
                    bySource.computeIfAbsent(position, k -> new ArrayList<>()).add(flow);
                }
            }
        }

        /** What a field or array access may touch: a static field's is its class's statics. */
        List<String> receivers(Node access) {
            if (access instanceof AccessFieldNode field) {
                return field.isStatic() ? List.of(typeName(field.field().getDeclaringClass()) + ".<statics>") : objects(field.object());
            }
            return access instanceof AccessIndexedNode indexed ? objects(indexed.array()) : null;
        }

        /** The objects, sorted, or null when the flows can't say. */
        List<String> objects(ValueNode reference) {
            TreeSet<String> names = new TreeSet<>();
            Deque<ValueNode> work = new ArrayDeque<>(List.of(reference));
            Set<ValueNode> seen = new HashSet<>();
            while (!work.isEmpty()) {
                ValueNode value = GraphUtil.unproxify(work.pop());
                if (!seen.add(value) || value.isNullConstant()) {
                    continue;
                }
                if (value instanceof ValuePhiNode phi) {
                    phi.values().forEach(work::push);
                    continue;
                }
                List<TypeFlow<?>> sources = sources(value);
                if (sources.isEmpty()) {
                    return null;
                }
                for (TypeFlow<?> source : sources) {
                    TypeState state = fold(source);
                    if (state == null) {
                        return null;
                    }
                    for (AnalysisObject object : state.objects(bb)) {
                        names.add(objectName(object));
                    }
                }
            }
            return new ArrayList<>(names);
        }

        private List<TypeFlow<?>> sources(ValueNode value) {
            List<TypeFlow<?>> found = new ArrayList<>();
            if (value instanceof ParameterNode parameter) {
                TypeFlow<?> flow = flows.getParameter(parameter.index());
                if (flow != null) {
                    found.add(flow);
                }
                return found;
            }
            NodeSourcePosition position = value.getNodeSourcePosition();
            for (TypeFlow<?> flow : position == null ? List.<TypeFlow<?>> of() : bySource.getOrDefault(position, List.of())) {
                boolean source = value instanceof LoadFieldNode load ? flow instanceof LoadFieldTypeFlow f && f.field().equals(load.field())
                                : value instanceof LoadIndexedNode ? flow instanceof LoadIndexedTypeFlow
                                : value instanceof AbstractNewObjectNode || value instanceof AllocatedObjectNode ? flow instanceof NewInstanceTypeFlow
                                : value instanceof ConstantNode && flow instanceof ConstantTypeFlow;
                if (source) {
                    found.add(flow);
                } else if (value instanceof Invoke && flow instanceof InvokeTypeFlow invoke && invoke.getActualReturn() != null) {
                    found.add(invoke.getActualReturn());
                }
            }
            return found;
        }

        /** The flow's state over every context, null if it saturated in any. */
        private TypeState fold(TypeFlow<?> original) {
            if (original.isSaturated()) {
                return null;
            }
            if (!(method.getTypeFlow() instanceof CallSiteSensitiveMethodTypeFlow sensitive)) {
                return original.getState();
            }
            TypeState state = TypeState.forEmpty();
            for (MethodFlowsGraph clone : sensitive.getFlows()) {
                TypeFlow<?> copy = clone.lookupCloneOf(bb, original);
                if (copy.isSaturated()) {
                    return null;
                }
                state = TypeState.forUnion(bb, state, copy.getState());
            }
            return state;
        }

        /**
         * An object by its type, and with an allocation-site-sensitive heap by
         * where it was allocated too: Examples$Counter@Examples.main([Ljava/lang/String;)V:9.
         * Heap contexts are left out, which merges objects: sound, if coarser.
         */
        static String objectName(AnalysisObject object) {
            String type = typeName(object.type());
            if (object instanceof AllocationContextSensitiveObject allocation) {
                return type + "@" + site(allocation.allocationLabel());
            }
            return object instanceof ConstantContextSensitiveObject ? type + "@constant" : type;
        }

        /**
         * Where a node or an allocation is, with the calls it was inlined through:
         * Examples.main([Ljava/lang/String;)V:9, null for nowhere.
         */
        static String site(BytecodePosition position) {
            if (position == null) {
                return null;
            }
            String at = methodKey(position.getMethod()) + ":" + position.getBCI();
            return position.getCaller() == null ? at : at + " in " + site(position.getCaller());
        }
    }

    private static Map<String, Object> exportBlock(HIRBlock block, StructuredGraph.ScheduleResult schedule,
                    Map<String, List<InvokeTypeFlow>> flowsByBci, PointsTo pointsTo, ObjectNames objectNames, Map<String, String> values, List<String> unsupported) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", block.getId());

        List<Object> preds = new ArrayList<>();
        for (int i = 0; i < block.getPredecessorCount(); i++) {
            preds.add(block.getPredecessorAt(i).getId());
        }
        out.put("preds", preds);

        // A merge's phis and a loop exit's proxies first: they are the values the
        // block receives, and the schedule does not list them among its nodes.
        List<Object> nodes = new ArrayList<>();
        if (block.getBeginNode() instanceof AbstractMergeNode merge) {
            for (PhiNode phi : merge.phis()) {
                nodes.add(exportScheduledNode(phi, schedule.getCFG(), flowsByBci, pointsTo, objectNames));
            }
        }
        if (block.getBeginNode() instanceof LoopExitNode exit) {
            for (ProxyNode proxy : exit.proxies()) {
                nodes.add(exportScheduledNode(proxy, schedule.getCFG(), flowsByBci, pointsTo, objectNames));
            }
        }
        for (Node node : schedule.nodesFor(block)) {
            if (!(node instanceof PhiNode) && !(node instanceof ProxyNode) && isScheduledValueOrEffect(node)) {
                nodes.add(exportScheduledNode(node, schedule.getCFG(), flowsByBci, pointsTo, objectNames));
            }
        }
        out.put("nodes", nodes);

        List<Object> ops = new ArrayList<>();
        for (FixedNode node : block.getNodes()) {
            Map<String, Object> op = exportNode(node, flowsByBci, values, unsupported);
            if (op != null) {
                ops.add(op);
            }
        }
        out.put("ops", ops);

        FixedNode end = block.getEndNode();
        List<Object> succs = new ArrayList<>();
        for (int i = 0; i < block.getSuccessorCount(); i++) {
            HIRBlock succ = block.getSuccessorAt(i);
            Map<String, Object> edge = new LinkedHashMap<>();
            edge.put("to", succ.getId());
            edge.put("label", edgeLabel(end, succ.getBeginNode()));
            succs.add(edge);
        }
        out.put("succs", succs);
        out.put("exit", end instanceof ControlSinkNode ? exitKind(end) : null);

        Map<String, Object> endInfo = new LinkedHashMap<>();
        endInfo.put("node", end.getClass().getSimpleName());
        endInfo.put("bci", bci(end));
        if (end instanceof IfNode ifNode) {
            endInfo.put("cond", ifNode.condition().getClass().getSimpleName());
        }
        out.put("end", endInfo);
        return out;
    }

    /**
     * An op for a node that touches memory, null for one that provably does
     * not. Anything else is recorded in {@code unsupported}.
     */
    private static Map<String, Object> exportNode(FixedNode node, Map<String, List<InvokeTypeFlow>> flowsByBci,
                    Map<String, String> values, List<String> unsupported) {
        if (node instanceof Invoke invoke) {
            return exportInvoke(invoke, flowsByBci);
        }
        if (node instanceof LoadFieldNode || node instanceof StoreFieldNode) {
            AccessFieldNode access = (AccessFieldNode) node;
            if (access.ordersMemoryAccesses()) {
                unsupported.add("ordered (volatile) access to " + fieldName(access.field()) + " at bci " + bci(node));
                return null;
            }
            Map<String, Object> op = new LinkedHashMap<>();
            op.put("kind", access instanceof StoreFieldNode ? "store" : "load");
            op.put("node", node.getId());
            op.put("bci", bci(node));
            op.put("field", fieldName(access.field()));
            op.put("object", access.isStatic() ? null : valueId(access.object(), values));
            if (access instanceof StoreFieldNode store) {
                op.put("value", valueId(store.value(), values));
            }
            return op;
        }
        if (node instanceof MembarNode || node instanceof FinalFieldBarrierNode) {
            Map<String, Object> op = new LinkedHashMap<>();
            op.put("kind", "fence");
            op.put("node", node.getId());
            op.put("bci", bci(node));
            return op;
        }
        // Anything else the translation takes from the scheduled nodes, or refuses itself.
        return null;
    }

    private static Map<String, Object> exportInvoke(Invoke invoke, Map<String, List<InvokeTypeFlow>> flowsByBci) {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("kind", "invoke");
        op.put("node", invoke.asFixedNode().getId());
        op.put("bci", invoke.bci());
        op.put("target", methodKey(invoke.getTargetMethod()));

        List<Object> callees = new ArrayList<>();
        List<InvokeTypeFlow> found = flowsByBci.get(flowKey(invoke));
        String status;
        if (found == null) {
            status = "missing";
        } else if (found.stream().noneMatch(InvokeTypeFlow::isFlowEnabled)) {
            status = "disabled";
        } else {
            for (InvokeTypeFlow flow : found) {
                for (AnalysisMethod callee : flow.getOriginalCallees()) {
                    if (!callees.contains(methodKey(callee))) {
                        callees.add(methodKey(callee));
                    }
                }
            }
            status = callees.isEmpty() ? "no-callees" : "ok";
        }
        callees.sort(null);
        op.put("callees", callees);
        op.put("flow", status);
        op.put("exception_edge", invoke instanceof InvokeWithExceptionNode);
        return op;
    }

    private static boolean isScheduledValueOrEffect(Node node) {
        if (node instanceof ExceptionObjectNode) {
            return true;
        }
        return !(node instanceof AbstractBeginNode || node instanceof AbstractEndNode || node instanceof VirtualState ||
                        node instanceof MethodCallTargetNode);
    }

    private static Map<String, Object> exportScheduledNode(Node node, ControlFlowGraph cfg, Map<String, List<InvokeTypeFlow>> flowsByBci, PointsTo pointsTo,
                    ObjectNames objectNames) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", node.getId());
        out.put("op", node.getClass().getSimpleName().replaceAll("Node$", ""));
        out.put("type", typeOf(node));
        if (node instanceof PhiNode phi) {
            AbstractMergeNode merge = phi.merge();
            List<Object> from = new ArrayList<>();
            for (int i = 0; i < phi.valueCount(); i++) {
                Map<String, Object> edge = new LinkedHashMap<>();
                edge.put("block", cfg.blockFor(merge.phiPredecessorAt(i)).getId());
                edge.put("value", phi.valueAt(i).getId());
                from.add(edge);
            }
            out.put("from", from);
            return out;
        }

        List<Object> in = new ArrayList<>();
        for (Position position : node.inputPositions()) {
            InputType kind = position.getInputType();
            Node input = position.get(node);
            if (input != null && (kind == InputType.Value || kind == InputType.Condition)) {
                in.add(input.getId());
            }
        }
        out.put("in", in);

        if (node instanceof ParameterNode param) {
            out.put("index", param.index());
        } else if (node instanceof ConstantNode constant) {
            out.put("value", stable(constant.getValue().toValueString())); // an object's type may be a hidden class
            if (constant.getValue() instanceof JavaConstant value && value.getJavaKind() == JavaKind.Object && !value.isNull()) {
                out.put("object", objectNames.name(constant, value)); // two objects of one type differ here
            }
        } else if (node instanceof AccessFieldNode access) {
            out.put("field", fieldName(access.field()));
            out.put("receivers", pointsTo.receivers(access));
            out.put("at", PointsTo.site(access.getNodeSourcePosition()));
        } else if (node instanceof AccessIndexedNode access) {
            out.put("kind", arrayPartition(access.elementKind()));
            out.put("receivers", pointsTo.receivers(access));
            out.put("at", PointsTo.site(access.getNodeSourcePosition()));
        } else if (node instanceof NewInstanceNode allocation) {
            out.put("class", typeName(allocation.instanceClass()));
        } else if (node instanceof NewArrayNode allocation) {
            out.put("kind", arrayPartition(allocation.elementType().getJavaKind()));
        } else if (node instanceof InstanceOfNode test) {
            out.put("class", typeName(test.type().getType()));
        } else if (node instanceof jdk.graal.compiler.nodes.ShortCircuitOrNode or) {
            out.put("negated", List.of(or.isXNegated(), or.isYNegated()));
        } else if (node instanceof VirtualInstanceNode object) {
            out.put("class", typeName(object.type()));
            List<Object> fields = new ArrayList<>();
            for (int i = 0; i < object.entryCount(); i++) {
                fields.add(fieldName(object.field(i)));
            }
            out.put("fields", fields);
        } else if (node instanceof VirtualArrayNode array) {
            out.put("kind", arrayPartition(array.componentType().getJavaKind()));
            out.put("length", array.entryCount());
        } else if (node instanceof CommitAllocationNode commit) {
            // The objects it makes, and their fields' or elements' values, object by object.
            List<Object> objects = new ArrayList<>();
            List<Object> values = new ArrayList<>();
            boolean locked = false;
            for (int i = 0; i < commit.getVirtualObjects().size(); i++) {
                objects.add(commit.getVirtualObjects().get(i).getId());
                locked |= !commit.getLocks(i).isEmpty();
            }
            for (ValueNode value : commit.getValues()) {
                values.add(value == null ? null : value.getId());
            }
            out.put("objects", objects);
            out.put("values", values);
            out.put("locked", locked);
        } else if (node instanceof AllocatedObjectNode allocated) {
            out.put("object", allocated.getVirtualObject().getId());
            out.put("receivers", pointsTo.objects(allocated)); // what it may be: where it was allocated
        } else if (node instanceof Invoke invoke) {
            List<Object> args = new ArrayList<>();
            for (ValueNode arg : invoke.callTarget().arguments()) {
                args.add(arg == null ? null : arg.getId());
            }
            out.put("args", args);
            Map<String, Object> call = exportInvoke(invoke, flowsByBci);
            for (String key : List.of("target", "callees", "flow", "exception_edge")) {
                out.put(key, call.get(key));
            }
        }
        out.put("bci", node instanceof ValueNode value ? bci(value) : -1);
        return out;
    }

    private static String typeOf(Node node) {
        if (node instanceof LogicNode) {
            return "cond";
        }
        if (!(node instanceof ValueNode value)) {
            return "void";
        }
        Stamp stamp = value.stamp(NodeView.DEFAULT);
        if (stamp instanceof AbstractObjectStamp) {
            return "ref";
        }
        if (stamp instanceof IntegerStamp integer) {
            return integer.getBits() > 32 ? "long" : "int";
        }
        if (stamp instanceof FloatStamp floating) {
            return floating.getBits() > 32 ? "double" : "float";
        }
        return "void";
    }

    private static boolean isControl(FixedNode node) {
        return node instanceof AbstractBeginNode || node instanceof AbstractEndNode || node instanceof ControlSinkNode ||
                        (node instanceof ControlSplitNode && !(node instanceof WithExceptionNode)) ||
                        node instanceof AbstractFixedGuardNode || node instanceof ValueAnchorNode;
    }

    /**
     * A fresh object is unreachable from any
     * other reference, so initializing it touches no existing partition; array
     * lengths and box contents never change.
     */
    private static boolean isFreshOrImmutable(FixedNode node) {
        return node instanceof AbstractNewObjectNode || node instanceof CommitAllocationNode || node instanceof BytecodeExceptionNode ||
                        node instanceof AbstractBoxingNode || node instanceof ArrayLengthNode;
    }

    private static String edgeLabel(FixedNode end, AbstractBeginNode to) {
        if (end instanceof IfNode ifNode) {
            return to == ifNode.trueSuccessor() ? "true" : to == ifNode.falseSuccessor() ? "false" : null;
        }
        if (end instanceof WithExceptionNode withException) {
            return to == withException.next() ? "normal" : to == withException.exceptionEdge() ? "exception" : null;
        }
        return null;
    }

    private static String exitKind(FixedNode end) {
        if (end instanceof ReturnNode) {
            return "return";
        }
        if (end instanceof UnwindNode) {
            return "unwind";
        }
        if (end instanceof AbstractDeoptimizeNode) {
            return "deopt";
        }
        return end.getClass().getSimpleName();
    }

    private static int valueId(ValueNode value, Map<String, String> values) {
        ValueNode root = GraphUtil.unproxify(value);
        values.putIfAbsent(String.valueOf(root.getId()), describe(root));
        return root.getId();
    }

    private static String describe(ValueNode value) {
        if (value instanceof ParameterNode param) {
            return "param" + param.index();
        }
        if (value instanceof ConstantNode constant) {
            return "const " + stable(constant.getValue().toValueString());
        }
        if (value instanceof NewInstanceNode allocation) {
            return "new " + typeName(allocation.instanceClass()) + "@" + bci(value);
        }
        if (value instanceof Invoke invoke) {
            return "result of " + methodName(invoke.getTargetMethod()) + "@" + invoke.bci();
        }
        if (value instanceof LoadFieldNode load) {
            return "load " + fieldName(load.field()) + "@" + bci(load);
        }
        return value.getClass().getSimpleName() + "#" + value.getId();
    }

    static int bci(ValueNode node) {
        NodeSourcePosition position = node.getNodeSourcePosition();
        return position == null ? -1 : position.getBCI();
    }

    static String methodName(ResolvedJavaMethod method) {
        return typeName(method.getDeclaringClass()) + "." + method.getName();
    }

    /** A class's name, as the export writes it: see {@link #nameHiddenClasses}. */
    static String typeName(ResolvedJavaType type) {
        return stable(type.toJavaName(true));
    }

    /** The name and the descriptor: what tells overloads apart. */
    /**
     * A method's invoke flows by the position the analysis gives them: for an invoke inlined
     * before it, the outermost call site, which more than one invoke may share.
     */
    static Map<String, List<InvokeTypeFlow>> flows(PointsToAnalysisMethod method) {
        Map<String, List<InvokeTypeFlow>> flows = new HashMap<>();
        for (InvokeTypeFlow flow : method.getTypeFlow().getMethodFlowsGraph().getInvokes()) {
            flows.computeIfAbsent(flow.getBci() + " " + methodKey(flow.getTargetMethod()), k -> new ArrayList<>()).add(flow);
        }
        return flows;
    }

    /** The key of an invoke's flows in {@link #flows}. */
    static String flowKey(Invoke invoke) {
        BytecodePosition position = invoke.asFixedNode().getNodeSourcePosition();
        while (position != null && position.getCaller() != null) {
            position = position.getCaller();
        }
        int bci = position != null ? position.getBCI()
                        : com.oracle.graal.pointsto.AbstractAnalysisEngine.syntheticSourcePosition(invoke.asFixedNode(), invoke.asFixedNode().graph().method()).getBCI();
        return bci + " " + methodKey(invoke.getTargetMethod());
    }

    /** An array element's partition, by element kind: boolean[] and byte[] share one, and every reference array is Object[]. */
    static String arrayPartition(JavaKind kind) {
        return switch (kind) {
            case Boolean, Byte -> "byte[]";
            case Object -> "Object[]";
            default -> kind.getJavaName() + "[]";
        };
    }

    static String methodKey(ResolvedJavaMethod method) {
        // An indirect call, as Native Image makes for a C function, names no method.
        return method == null ? "<indirect>" : methodName(method) + stable(method.getSignature().toMethodDescriptor());
    }

    static String fieldName(ResolvedJavaField field) {
        return typeName(field.getDeclaringClass()) + "." + field.getName();
    }

    static String toJson(Object value, int depth) {
        StringBuilder sb = new StringBuilder();
        writeJson(sb, value, depth);
        return sb.toString();
    }

    private static void writeJson(StringBuilder sb, Object value, int depth) {
        if (value instanceof Map<?, ?> map) {
            boolean flat = map.values().stream().allMatch(GraphExport::isFlat);
            sb.append('{');
            int i = 0;
            for (Map.Entry<?, ?> e : map.entrySet()) {
                separate(sb, i++, flat, depth + 1);
                quote(sb, String.valueOf(e.getKey()));
                sb.append(": ");
                writeJson(sb, e.getValue(), depth + 1);
            }
            close(sb, flat || map.isEmpty(), depth);
            sb.append('}');
        } else if (value instanceof List<?> list) {
            boolean flat = list.stream().allMatch(GraphExport::isScalar);
            sb.append('[');
            for (int i = 0; i < list.size(); i++) {
                separate(sb, i, flat, depth + 1);
                writeJson(sb, list.get(i), depth + 1);
            }
            close(sb, flat || list.isEmpty(), depth);
            sb.append(']');
        } else if (value instanceof String s) {
            quote(sb, s);
        } else {
            sb.append(value);
        }
    }

    private static boolean isScalar(Object value) {
        return !(value instanceof Map<?, ?>) && !(value instanceof List<?>);
    }

    private static boolean isFlat(Object value) {
        return isScalar(value) || (value instanceof List<?> list && list.stream().allMatch(GraphExport::isScalar));
    }

    private static void separate(StringBuilder sb, int index, boolean flat, int depth) {
        if (index > 0) {
            sb.append(flat ? ", " : ",");
        }
        if (!flat) {
            sb.append('\n').append("  ".repeat(depth));
        }
    }

    private static void close(StringBuilder sb, boolean flat, int depth) {
        if (!flat) {
            sb.append('\n').append("  ".repeat(depth));
        }
    }

    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                default -> sb.append(c < 0x20 ? String.format("\\u%04x", (int) c) : String.valueOf(c));
            }
        }
        sb.append('"');
    }
}
