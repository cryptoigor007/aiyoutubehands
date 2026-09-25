# bash completion for ayh
_ayh_completions() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    local cmds="doctor version auth channel calendar quota ai video upload"
    local auth_cmds="status login logout"
    local cal_cmds="list grid add"
    local quota_cmds="status"
    local ai_cmds="title description tags script thumbnail"
    local video_cmds="info list"
    local upload_cmds="prepare"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return
    fi
    case "${COMP_WORDS[1]}" in
        auth) COMPREPLY=( $(compgen -W "${auth_cmds}" -- "${cur}") ) ;;
        calendar) COMPREPLY=( $(compgen -W "${cal_cmds}" -- "${cur}") ) ;;
        quota) COMPREPLY=( $(compgen -W "${quota_cmds}" -- "${cur}") ) ;;
        ai) COMPREPLY=( $(compgen -W "${ai_cmds}" -- "${cur}") ) ;;
        video) COMPREPLY=( $(compgen -W "${video_cmds}" -- "${cur}") ) ;;
        upload) COMPREPLY=( $(compgen -W "${upload_cmds}" -- "${cur}") ) ;;
    esac
}
complete -F _ayh_completions ayh
