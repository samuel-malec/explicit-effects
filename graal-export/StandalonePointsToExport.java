import com.oracle.graal.pointsto.PointsToAnalysis;
import com.oracle.graal.pointsto.export.PointsToExport;
import com.oracle.graal.pointsto.standalone.PointsToAnalyzer;

/**
 * Runs the standalone points-to analyzer on a program and exports what it found with
 * {@link PointsToExport}, which lives in the graal tree's points-to analysis. The paths come as
 * system properties, as run-dump.sh passes them: {@code dump.json} for the facts of every reachable
 * method, {@code dump.ir} for those and the program's graphs, either empty to skip it. The
 * program is {@code dump.filter}, a class-name prefix: empty for every class outside the
 * platform's packages, * for all.
 */
public class StandalonePointsToExport {

    public static void main(String[] args) {
        PointsToAnalyzer analyzer = PointsToAnalyzer.createAnalyzer(args);
        analyzer.run();
        PointsToAnalysis bb = (PointsToAnalysis) (Object) analyzer.getResultAnalysis();
        PointsToExport.export(bb, analyzer.getResultUniverse(), System.getProperty("dump.json", ""), System.getProperty("dump.ir", ""), System.out, false,
                        System.getProperty("dump.filter", ""));
    }
}
