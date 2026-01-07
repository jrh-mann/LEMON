def determine_workflow_outcome(inputs):
    under_specialist_clinic = inputs.get('under_specialist_clinic', False)
    total_cholesterol = inputs.get('total_cholesterol', 0)
    prevention_type = inputs.get('prevention_type', 'Primary')
    taking_lipid_lowering_therapy = inputs.get('taking_lipid_lowering_therapy', False)
    optimised_on_treatment = inputs.get('optimised_on_treatment', False)
    qrisk2_3_score = inputs.get('qrisk2_3_score', 0)
    taking_maximally_tolerated_statin = inputs.get('taking_maximally_tolerated_statin', False)
    ldl_cholesterol = inputs.get('ldl_cholesterol', 0)
    months_on_inclisiran = inputs.get('months_on_inclisiran', 0)

    if total_cholesterol > 7.5:
        if under_specialist_clinic:
            return "no further action"
        else:
            if optimised_on_treatment:
                return "consider lipid clinic referral"
            else:
                return "send lipid lowering therapy accurx with self booking link"
    elif total_cholesterol > 5 and total_cholesterol <= 7.5:
        # raised
        if taking_lipid_lowering_therapy:
            if optimised_on_treatment:
                return "mark as no further action"
            else:
                return "send lipid lowering therapy accurx with self booking link"
        else:
            if prevention_type == "Primary":
                if qrisk2_3_score >= 10:
                    return "send lipid lowering therapy accurx with self booking link"
                else:
                    # <10%
                    return "send high cholesterol low qrisk accurx with self booking link"
            else:
                # secondary
                if taking_maximally_tolerated_statin:
                    if ldl_cholesterol <= 2:
                        return "no further action"
                    elif ldl_cholesterol > 2 and ldl_cholesterol <= 2.5:
                        return "add in ezetimibe"
                    else:
                        # >= 2.6
                        return "initiate inclisiran"
                        # then you neede to wait 3 months and check ldl again, not sure how to do this here
                else:
                    return "send lipid lowering therapy accurx with self booking link"
    else:
        # normal
        return "mark as satisfactory"
