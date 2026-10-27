"""Validate background correspondences. No image extractor or model is claimed here."""
import math
import statistics
from ..pipeline_v4 import finite

class BackgroundStability:
    def __init__(self, reference_id=None, test_mode=False, allow_external=False):
        self.reference_id=reference_id
        self.test_mode=test_mode
        self.allow_external=allow_external

    def assess(self, frame_id, timestamp, session, context):
        def result(status,reason,**details):
            return dict(details,status=status,reason=reason,stable=status=="STABLE")
        if not isinstance(context,dict) or not self.reference_id:
            return result("UNKNOWN","no_verified_background_evidence")
        provider=context.get("provider")
        if provider=="controlled_fixture":
            if not self.test_mode:return result("UNKNOWN","synthetic_evidence_not_allowed")
        elif provider=="background_correspondences":
            if not self.allow_external:return result("UNKNOWN","real_image_provider_not_enabled_or_validated")
        else:
            return result("UNKNOWN","untrusted_provider")
        if context.get("frame_id")!=str(frame_id) or context.get("source_session")!=session:
            return result("UNKNOWN","frame_or_session_mismatch")
        if context.get("reference_id")!=self.reference_id:
            return result("UNKNOWN","calibration_reference_mismatch")
        try:
            if abs(finite(context["timestamp"])-timestamp)>1e-8:
                return result("UNKNOWN","stale_background_evidence")
            pairs=context["matches"]
            if not isinstance(pairs,list) or len(pairs)<20:
                return result("UNKNOWN","insufficient_background_matches")
            displacements=[];quadrants=set()
            for pair in pairs:
                if not isinstance(pair,(list,tuple)) or len(pair)!=5:
                    return result("UNKNOWN","invalid_match")
                x,y,u,v,error=[finite(a) for a in pair]
                if not all(0<=a<=1 for a in (x,y,u,v)) or error<0 or error>.002:
                    continue
                # Require background feature provenance, not hand/painting-only points.
                if .2<x<.8 and .2<y<.8:
                    continue
                quadrants.add((int(x>=.5),int(y>=.5)))
                displacements.append((u-x,v-y))
            if len(displacements)<20 or len(quadrants)<3:
                return result("UNKNOWN","poor_background_coverage")
            dx=statistics.median(p[0] for p in displacements)
            dy=statistics.median(p[1] for p in displacements)
            residuals=[math.hypot(x-dx,y-dy) for x,y in displacements]
            inliers=sum(r<=.002 for r in residuals)/float(len(residuals))
            drift=sorted(math.hypot(x,y) for x,y in displacements)
            p95=drift[int(math.ceil(.95*len(drift)))-1]
            if inliers<.8:
                return result("MOVING","inconsistent_reference_geometry",inlier_ratio=inliers,reference_drift_p95=p95)
            if p95>.005:
                return result("MOVING","camera_pose_changed_from_reference",inlier_ratio=inliers,reference_drift_p95=p95)
            return result("STABLE","background_matches_reference",inlier_ratio=inliers,reference_drift_p95=p95,
                          image_extraction_validated=False,controlled_fixture=provider=="controlled_fixture")
        except (ValueError,TypeError,KeyError,OverflowError):
            return result("UNKNOWN","malformed_background_evidence")
