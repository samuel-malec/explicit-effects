import java.util.List;

import org.graalvm.nativeimage.c.function.CFunctionPointer;
import org.graalvm.nativeimage.hosted.Feature;
import org.graalvm.nativeimage.hosted.RuntimeClassInitialization;
import org.graalvm.word.WordFactory;

import com.oracle.svm.core.c.InvokeJavaFunctionPointer;
import com.oracle.svm.core.deopt.DeoptTest;
import com.oracle.svm.graal.SubstrateGraalUtils;
import com.oracle.svm.graal.hosted.runtimecompilation.RuntimeCompilationFeature;
import com.oracle.svm.graal.meta.SubstrateMethod;
import com.oracle.svm.hosted.FeatureImpl.BeforeAnalysisAccessImpl;
import com.oracle.svm.shared.NeverInline;
import com.oracle.svm.shared.util.ModuleSupport;
import com.oracle.svm.shared.util.VMError;

import jdk.vm.ci.code.InstalledCode;

/**
 * A method deoptimized while it holds a lock on an object only one thread reaches, in two ways. The version
 * of the method that a deoptimization resumes in (the one the image was built with for that purpose) must
 * release the lock at the end of the region, whatever took it.
 *
 * <ul>
 * <li>The method is compiled while the program runs ({@link #main} registers it for runtime compilation,
 * compiles it and calls it through a function pointer), and the compiled code is invalidated by a call
 * inside the locked region. The compiled code took the lock, so the version it resumes in must release it;
 * if the build had removed the monitors from that version, the thread would still hold the lock when the
 * method returns.</li>
 * <li>The method is the one the image was built with, marked as one that can deoptimize for testing, and
 * the stress test of {@code -H:+DeoptimizeAll} deoptimizes it inside the region. If the build had removed
 * the monitors from the code of the image and left them in the version it resumes in, that version would
 * release a lock nobody took.</li>
 * </ul>
 *
 * A correct build prints {@code false} for the first and {@code ok} for the second.
 */
public class DeoptimizedLocks {

    static final class Cell {
        int value;
    }

    static InstalledCode installed;
    static SubstrateMethod method;

    @NeverInline("The call stays a call in the compiled code, and the lock is held across it")
    static void invalidate() {
        if (installed != null) {
            installed.invalidate();
        }
    }

    /** Takes the object to something the compiler can't see into, so that it is a real object with a real lock. */
    @NeverInline("The object has to exist when the lock is taken")
    static void touch(Cell cell) {
        cell.value++;
    }

    @DeoptTest
    public static Cell run() {
        Cell cell = new Cell();
        touch(cell);
        synchronized (cell) {
            cell.value++;
            invalidate();
            cell.value++;
        }
        return cell;
    }

    interface Entry extends CFunctionPointer {
        @InvokeJavaFunctionPointer
        Cell invoke();
    }

    public static class RegisterMethodsFeature implements Feature {
        public RegisterMethodsFeature() {
            ModuleSupport.accessPackagesToClass(ModuleSupport.Access.EXPORT, RegisterMethodsFeature.class, false,
                            "org.graalvm.nativeimage.builder",
                            "com.oracle.svm.graal", "com.oracle.svm.graal.hosted.runtimecompilation", "com.oracle.svm.hosted", "com.oracle.svm.core.util");
            ModuleSupport.accessPackagesToClass(ModuleSupport.Access.EXPORT, RegisterMethodsFeature.class, false,
                            "jdk.internal.vm.ci",
                            "jdk.vm.ci.code");
        }

        @Override
        public List<Class<? extends Feature>> getRequiredFeatures() {
            return List.of(RuntimeCompilationFeature.class);
        }

        @Override
        public void beforeAnalysis(BeforeAnalysisAccess a) {
            BeforeAnalysisAccessImpl config = (BeforeAnalysisAccessImpl) a;
            RuntimeClassInitialization.initializeAtBuildTime(DeoptimizedLocks.class);
            RuntimeCompilationFeature runtimeCompilationFeature = RuntimeCompilationFeature.singleton();
            runtimeCompilationFeature.initializeRuntimeCompilationForTesting(config);
            try {
                method = runtimeCompilationFeature.prepareMethodForRuntimeCompilation(DeoptimizedLocks.class.getMethod("run"), config);
            } catch (NoSuchMethodException ex) {
                throw VMError.shouldNotReachHere(ex);
            }
        }
    }

    public static void main(String[] args) {
        /*
         * The stress test deoptimizes a frame at the first point it has not seen yet, so each call goes one
         * point further, into the locked region in time.
         */
        String image = "ok";
        for (int i = 0; i < 20 && image.equals("ok"); i++) {
            try {
                Cell cell = run();
                if (cell.value != 3 || Thread.holdsLock(cell)) {
                    image = "wrong: value " + cell.value + ", holds the lock " + Thread.holdsLock(cell);
                }
            } catch (IllegalMonitorStateException e) {
                image = "IllegalMonitorStateException";
            }
        }
        System.out.println("image code deoptimized in the region: " + image);

        installed = SubstrateGraalUtils.compileAndInstall(method);
        Entry entry = WordFactory.pointer(installed.getEntryPoint());
        Cell cell = entry.invoke();
        System.out.println("compiled code deoptimized in the region, value " + cell.value + ", holds the lock after the method returned: " + Thread.holdsLock(cell));
    }
}
