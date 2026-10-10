import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

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
import com.oracle.graal.pointsto.meta.AnalysisMethod;
import com.oracle.graal.pointsto.meta.PointsToAnalysisMethod;
import com.oracle.graal.pointsto.phases.InlineBeforeAnalysis;
import com.oracle.graal.pointsto.typestate.TypeState;

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
import jdk.graal.compiler.nodes.virtual.AllocatedObjectNode;
import jdk.graal.compiler.nodes.virtual.CommitAllocationNode;
import jdk.vm.ci.code.BytecodePosition;
import jdk.vm.ci.meta.ResolvedJavaField;
import jdk.vm.ci.meta.ResolvedJavaMethod;

/**
 * Exports a method's Graal IR annotated with points-to analysis information
 */
final class GraphExport {

    private GraphExport() {
    }

    static Map<String, Object> export(PointsToAnalysis bb, PointsToAnalysisMethod method) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", methodName(method));
        out.put("descriptor", method.getSignature().toMethodDescriptor());
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

        Map<Integer, InvokeTypeFlow> flowsByBci = new TreeMap<>();
        for (InvokeTypeFlow flow : method.getTypeFlow().getMethodFlowsGraph().getInvokes()) {
            if (flowsByBci.put(flow.getBci(), flow) != null) {
                unsupported.add("two invoke flows at bci " + flow.getBci());
            }
        }

        PointsTo pointsTo = new PointsTo(bb, method);
        Map<String, String> values = new TreeMap<>();
        List<Object> blocks = new ArrayList<>();
        for (HIRBlock block : cfg.reversePostOrder()) {
            blocks.add(exportBlock(block, schedule, flowsByBci, pointsTo, values, unsupported));
        }
        out.put("entry", cfg.getStartBlock().getId());
        out.put("blocks", blocks);
        out.put("values", values);
        return out;
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
                return field.isStatic() ? List.of(field.field().getDeclaringClass().toJavaName(true) + ".<statics>") : objects(field.object());
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
            String type = object.type().toJavaName(true);
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
                    Map<Integer, InvokeTypeFlow> flowsByBci, PointsTo pointsTo, Map<String, String> values, List<String> unsupported) {
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
                nodes.add(exportScheduledNode(phi, schedule.getCFG(), flowsByBci, pointsTo));
            }
        }
        if (block.getBeginNode() instanceof LoopExitNode exit) {
            for (ProxyNode proxy : exit.proxies()) {
                nodes.add(exportScheduledNode(proxy, schedule.getCFG(), flowsByBci, pointsTo));
            }
        }
        for (Node node : schedule.nodesFor(block)) {
            if (!(node instanceof PhiNode) && !(node instanceof ProxyNode) && isScheduledValueOrEffect(node)) {
                nodes.add(exportScheduledNode(node, schedule.getCFG(), flowsByBci, pointsTo));
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
    private static Map<String, Object> exportNode(FixedNode node, Map<Integer, InvokeTypeFlow> flowsByBci,
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
        if (isControl(node) || isFreshOrImmutable(node)) {
            return null;
        }
        unsupported.add(node.getClass().getSimpleName() + " at bci " + bci(node));
        return null;
    }

    private static Map<String, Object> exportInvoke(Invoke invoke, Map<Integer, InvokeTypeFlow> flowsByBci) {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("kind", "invoke");
        op.put("node", invoke.asFixedNode().getId());
        op.put("bci", invoke.bci());
        op.put("target", methodKey(invoke.getTargetMethod()));

        List<Object> callees = new ArrayList<>();
        InvokeTypeFlow flow = flowsByBci.get(invoke.bci());
        String status;
        if (flow == null) {
            status = "missing";
        } else if (!flow.isFlowEnabled()) {
            status = "disabled";
        } else {
            for (AnalysisMethod callee : flow.getOriginalCallees()) {
                callees.add(methodKey(callee));
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

    private static Map<String, Object> exportScheduledNode(Node node, ControlFlowGraph cfg, Map<Integer, InvokeTypeFlow> flowsByBci, PointsTo pointsTo) {
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
            out.put("value", constant.getValue().toValueString());
        } else if (node instanceof AccessFieldNode access) {
            out.put("field", fieldName(access.field()));
            out.put("receivers", pointsTo.receivers(access));
            out.put("at", PointsTo.site(access.getNodeSourcePosition()));
        } else if (node instanceof AccessIndexedNode access) {
            out.put("receivers", pointsTo.receivers(access));
            out.put("at", PointsTo.site(access.getNodeSourcePosition()));
        } else if (node instanceof NewInstanceNode allocation) {
            out.put("class", allocation.instanceClass().toJavaName(true));
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
            return "const " + constant.getValue().toValueString();
        }
        if (value instanceof NewInstanceNode allocation) {
            return "new " + allocation.instanceClass().toJavaName(true) + "@" + bci(value);
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
        return method.getDeclaringClass().toJavaName(true) + "." + method.getName();
    }

    /** The name and the descriptor: what tells overloads apart. */
    static String methodKey(ResolvedJavaMethod method) {
        // An indirect call, as Native Image makes for a C function, names no method.
        return method == null ? "<indirect>" : methodName(method) + method.getSignature().toMethodDescriptor();
    }

    static String fieldName(ResolvedJavaField field) {
        return field.getDeclaringClass().toJavaName(true) + "." + field.getName();
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
