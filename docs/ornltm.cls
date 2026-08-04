% !TEX root = ornl-template-example.tex
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% File: ornltm.cls
% Authors: Seth R Johnson, Sam Crawford,* and John Batson
% *Corresponding author, crawfordst@ornl.gov
% Date: Tuesday, February 10, 2026 @ 16:06
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\NeedsTeXFormat{LaTeX2e}[1995/12/01]
\ProvidesClass{ornltm}[2018/10/13 ORNL Technical Memorandum class]

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% OPTIONS
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Define default option
\newif\if@tm
\newif\if@spr
\newif\if@ltr

% Process options
\DeclareOption{tm}{\@tmtrue}
\DeclareOption{spr}{\@sprtrue}
\DeclareOption{ltr}{\@ltrtrue}

\ProcessOptions\relax

% If no options were provided, set default to 'tm'
\if@tm
  % Option 'tm' is selected
\else
  \if@spr
    % Option 'spr' is selected
  \else
    \if@ltr
      % Option 'ltr' is selected
    \else
      % No options provided, default to 'tm'
      \@tmtrue
    \fi
  \fi
\fi


\LoadClass[11pt,letterpaper]{article}

% Set \today to just month and year. \date{} can also be specified in example.
\renewcommand{\today}{\ifcase \month \or January\or February\or March\or %
April\or May \or June\or July\or August\or September\or October\or November\or %
December\fi~\number \year}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% STYLING
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\RequirePackage{wallpaper} % Background on cover page
\RequirePackage{adjustbox} % Used to keep author block within front cover
\RequirePackage{fancyhdr} % Headers and footers
\RequirePackage{emptypage} % Hide footers on blank pages
\RequirePackage[pdfusetitle]{hyperref} % url and links in PDF
\RequirePackage{longtable} % Allows tables to span multiple pages
\RequirePackage{acro} % Add support for abbreviations
\RequirePackage{array} % Add support for tabulars
\RequirePackage{tocloft} % Table of contents styling
\RequirePackage{color} % Colored fonts and boxes
\RequirePackage{framed} % Framed notice boxes
\FrameSep4pt % Sets padding for framed boxes.
\RequirePackage{seqsplit} % For splitting unruly character strings
\RequirePackage{etoolbox} % Patch for all caps first- and second-order headings in TOC
\RequirePackage{graphicx}
\usepackage{pdfpages} % Enables you to add PDFs as if they were pages in your doc.
\usepackage{ifpdf} % Used to identify presence of a file.
\usepackage{wrapfig} % Enables wrapping figures in text.

% Load document style
\RequirePackage{ornltm-style}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% VARIABLES
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% Division or program name
\newif\if@divisiondefined
\@divisiondefinedfalse
\def\@division{DIVISION NAME UNDEFINED%
\PackageWarning{ornltm}{No division name has been defined.}}
\newcommand{\division}[1]{\def\@division{#1}\@divisiondefinedtrue}

% Use the \reportnum command to define a report number.
\newif\if@reportnumdefined
\@reportnumdefinedfalse
\def\@reportnum{ORNL/XX-XXXX/XXX%
\PackageWarning{ornltm}{No report number has been defined.}}
\newcommand{\reportnum}[1]{\def\@reportnum{#1}\@reportnumdefinedtrue}

% Use the \sponsornum command to define a sponsor number.
\newif\if@sponsornumdefined
\@sponsornumdefinedfalse
\def\@sponsornum{%
}
\newcommand{\sponsornum}[1]{\def\@sponsornum{#1}\@sponsornumdefinedtrue}

\newif\if@reportdraft
\@reportdraftfalse
\newcommand{\reportdraft}{\@reportdrafttrue}

\def\@affiliation{\relax}
\newcommand{\affiliation}[1]{\def\@affiliation{#1}}
\newcommand{\affilnum}[1]{\texorpdfstring{\textsuperscript{#1}}{}}

% Adding sponsor logo definitions.
\newif\if@SponsorLogoOnedefined
\@SponsorLogoOnedefinedfalse
\newcommand{\SponsorLogoOne}[1]{\def\@SponsorLogoOne{#1}\@SponsorLogoOnedefinedtrue}

\newif\if@SponsorLogoTwodefined
\@SponsorLogoTwodefinedfalse
\newcommand{\SponsorLogoTwo}[1]{\def\@SponsorLogoTwo{#1}\@SponsorLogoTwodefinedtrue}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% PRINT AUTHORS (limits authors to 5 + et al. on cover page)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\newcommand\printauthors{%
  \begingroup
  \parskip=0pt % no extra vertical glue before/between lines
  \parindent=0pt % no first-line indent
  \leavevmode\noindent % start cleanly in horizontal mode
  \newcount\auth@count \auth@count=0
  \def\auth@break{\unskip\hfil\break}% line break w/o paragraph skip; eat space before
  % Recursive parser
  \def\auth@do##1\and##2\auth@end{%
    \advance\auth@count by 1\relax
    \ifnum\auth@count<5
      ##1%
      \if\relax\detokenize{##2}\relax
        % done
      \else
        \auth@break
        \expandafter\auth@do##2\auth@end
      \fi
    \else
      ##1%
      \if\relax\detokenize{##2}\relax
        % exactly 5 authors — done
      \else
        \unskip\space et al.%
      \fi
    \fi
  }%
  \expandafter\auth@do\@author\and\auth@end
  \par\endgroup
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Added for CRADA (remains blank if CRADA is undefined)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Uncomment the \crada{...} command in the document and add number.
\newif\if@cradadefined
\@cradadefinedfalse
\newcommand{\crada}[1]{\def\@crada{#1}\@cradadefinedtrue}

\newif\if@cradaprotecteddefined
\@cradaprotecteddefinedfalse

\newcommand{\cradaprotected}[2]{%
  \def\@cradaprotectedfirst{#1}%
  \def\@cradaprotectedsecond{#2}%
  \@cradaprotecteddefinedtrue%
}

% Creating \printcrada command to simplify CRADA implementation
\newcommand{\printcrada}{%
\if@cradadefined{%
  \noindent{\footnotesize\textbsf{CONTROLLED UNCLASSIFIED INFORMATION -- EXPORT CONTROLLED INFORMATION}}%
  }%
\else\relax
\fi%
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Added for Export Control (remains blank if Export is undefined)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Uncomment the \export{...} command in the document if export controlled.

\newif\if@exportdefined
\@exportdefinedfalse
\def\@export{EXPORT AUTH UNDEFINED%
\PackageWarning{ornltm}{No export authority has been defined.}}

\newcommand{\export}[5]{%
  \def\@exportname{#1}%
  \def\@exportemail{#2}%
  \def\@exportphone{#3}%
  \def\@exportdate{#4}%
  \def\@exportreg{#5}%
  \@exportdefinedtrue

  % Check arguments and warn if empty
  \IfStrEq{\@exportemail}{}{%
    \PackageWarning{ornltm}{Reviewer name (argument 1) not defined in \string\export}%
  }{}%
  \IfStrEq{\@exportemail}{}{%
    \PackageWarning{ornltm}{Email address (argument 2) not defined in \string\export}%
  }{}%
  \IfStrEq{\@exportphone}{}{%
    \PackageWarning{ornltm}{Phone number (argument 3) not defined in \string\export}%
  }{}%
  \IfStrEq{\@exportdate}{}{%
    \PackageWarning{ornltm}{Date (argument 4) not defined in \string\export}%
  }{}%
  \IfStrEq{\@exportreg}{}{%
    \PackageWarning{ornltm}{Regulation (argument 5) not defined in \string\export}%
  }{}%
}

\newcommand{\exportname}{\@exportname}
\newcommand{\exportemail}{\@exportemail}
\newcommand{\exportphone}{\@exportphone}
\newcommand{\exportdate}{\@exportdate}
\newcommand{\exportreg}{\@exportreg}

% Creating \printExport command to simplify export controlled implementation
\newcommand{\printExport}{%
\if@exportdefined{%
\if@cuidefined{%
  \vspace{0.5em}
  \begin{framed}
  \begin{center}
    \textbsf{EXPORT CONTROLLED INFORMATION} \\
  \end{center}
      \textsf{\small%
      Contains technical information whose export is restricted by
      \@exportreg. Violations may result in administrative,
      civil, and/or criminal penalties. Limit dissemination to US persons.
      The cognizant program manager must approve other dissemination.
      This notice must not be separated from the attached document.\\
      \vspace{0.5em}
      \textbf{Reviewer:} \@exportname \\
      \textbf{Email:} \@exportemail \\
      \textbf{Phone Number:} \@exportphone \\
      \textbf{Date:} \@exportdate
      }
  \end{framed}
}%
\else{\PackageWarning{ornltm}{Export Controlled option requires CUI option.}}
\textcolor{red}{\large\textbsf{Warning: Export Controlled option requires CUI option.}}
\fi%
}%
\else\relax
\fi%
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Added for CUI (remains blank if CUI is undefined)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Uncomment the \cui{...} command in the document if CUI.
\newif\if@cuidefined
\@cuidefinedfalse
\newcommand{\cui}[3]{%
  \def\@cuiCat{#1}\@cuidefinedtrue
  \def\@cuiDA{#2}%
  \def\@cuiPh{#3}%

  % Check arguments and warn if empty
  \IfStrEq{\@cuiCat}{}{%
    \PackageWarning{ornltm}{CUI category (argument 1) not defined in \string\cui}%
  }{}%
  \IfStrEq{\@cuiDA}{}{%
    \PackageWarning{ornltm}{CUI designated authority (argument 2) not defined in \string\cui}%
  }{}%
  \IfStrEq{\@cuiPh}{}{%
    \PackageWarning{ornltm}{CUI phone number (argument 3) not defined in \string\cui}%
  }{}%
}

\newcommand{\cuiCat}{\@cuiCat}
\newcommand{\cuiDA}{\@cuiDA}
\newcommand{\cuiPh}{\@cuiPh}

% Creating \printcui command to simplify CUI implementation
\newcommand{\printcui}{
\begin{center}
\if@cuidefined{\large\textbsf{\par\@cuiCat}}
\else\relax
\fi%
\end{center}
}


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% \PrintNotices simplifies execution of front notices for SPR and TM.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\newcommand{\PrintNotices}{%
  % Configure notices for front cover.
  \if@cradadefined% First check if CRADA is defined.
    \if@cradaprotecteddefined% Next check to see if it is PROTECTED CRADA
      \if@cuidefined% Only show protected box if CUI is also defined
        \begin{framed} % Begin PROTECTED CRADA BOX IF SO.
        \begin{center}
        \textbsf{\normalsize\par PROTECTED CRADA INFORMATION \\}%
        \end{center}
        \textsf{\small
        \begin{sloppypar}
        This product contains Protected CRADA Information that was produced in
        \underline{\smash{\@date}} under \underline{\smash{\@crada}} and is not to be further disclosed for a
        period of \underline{\smash{\@cradaprotectedfirst}} from the date it was produced except as expressly
        provided for in the CRADA.%
        \end{sloppypar}
        }
        \end{framed}
      \else
        \PackageWarning{ornltm}{Protected CRADA requires CUI to be defined. Use the 'cui' option.}
        \textcolor{red}{\large\textbsf{Warning: CUI required for CRADA.}}
      \fi
    \else% Otherwise (not protected), print CRADA final report notice.
      \if@reportdraft
        % Do nothing if it's a draft
      \else
        \if@cuidefined% Only show final report notice if CUI is defined
          \begin{center}
          \begin{framed}
          \textbsf{\normalsize\par CRADA final report for \\
          \@crada}%
          \end{framed}
          \end{center}
          \vspace{1em}
        \else
          \PackageWarning{ornltm}{CRADA final report requires CUI to be defined. Use the 'cui' option.}
          \textcolor{red}{\large\textbsf{Warning: CUI required for CRADA.}}
        \fi
      \fi
    \fi
  \fi
}
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% \PublicRelease simplifies execution of front public release notice.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\newcommand{\PublicRelease}{%
  % Ensure restricted, CRADA protected, and CUI documents are *not* marked for public release
  % if the document is *not* marked as draft.
  \if@cuidefined
    \begin{center}
    \textbsf{\normalsize Controlled by: \@cuiDA, \@cuiPh}%
    \end{center}
  \else
    \if@restrictdefined
      \printrestrict
    \else
      \if@exportdefined
        % Do nothing if export is defined
      \else
        \if@cradaprotecteddefined
          % Do nothing if cradaprotected is defined
        \else
          \if@reportdraft
            % Do nothing if draft
          \else
            \if@cradadefined
              % Do nothing if CRADA is defined
            \else
              % If not draft, CUI, CRADA, or otherwise restricted, then unlimited distro.
              \begin{center}
              \textbsf{\normalsize Approved for public release. \\
              Distribution is unlimited.}%
              \end{center}
            \fi
          \fi
        \fi
      \fi
    \fi
  \fi
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Use the \restrict command to add qualifications to the document's restriction.
% (e.g., business sensitive).
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\newif\if@restrictdefined
\@restrictdefinedfalse
\newcommand{\restrict}[1]{\def\@restrict{#1}\@restrictdefinedtrue}

% Creating \printrestrict command to simplify restricted footer
\newcommand{\printrestrict}{
  \begin{center}
  \if@cuidefined % CUI supercedes restrict, so do nothing if CUI.
  \else%
  \if@restrictdefined{\large\textbsf{\@restrict}}
  \else\relax%
  \fi%
  \fi
  \end{center}
  }  

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Define ORNL title photo with default
\def\@ornltmtitlephoto{luggage/ornltm-titlephoto.jpg}
\newcommand{\reportphoto}[1]{\def\@ornltmtitlephoto{#1}}

% Define uppercase names
\newcommand\ornltmforewordname{FOREWORD}
\newcommand\ornltmabstractname{ABSTRACT}
\newcommand\ornltmlofname{LIST OF FIGURES}
\newcommand\ornltmlotname{LIST OF TABLES}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% COVER PAGE
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% Bold sans-serif
\newcommand{\textbsf}[1]{{\bfseries\sffamily #1}}
% Bold italics
\newcommand{\textbi}[1]{{\bfseries\itshape #1}}
% ORNL official green color
\definecolor{ornlgreen}{RGB}{0,121,52}
% Green can render as this color (???)
\definecolor{ornldarkgreen}{RGB}{52,118,60} % from included ORNL logo

% Footer for cover page
\fancypagestyle{coverpage}
{
  \renewcommand\headrulewidth{0pt}
  \fancyhf{}
}

\newcommand{\@restrictfootwarning}[1]{%
  \vspace{-2\baselineskip}\par
  \makebox[\textwidth][c]{\textbsf{#1}}\par
}

%% Limiting title size (Shrinks font if title is too long)
\newsavebox{\titlebox}
\newcommand{\fittitle}[2][\textwidth]{% #1=max width, #2=max height
  \sbox{\titlebox}{%
    \parbox{#1}{\Huge\textbsf{\@title}}%
  }%
  \ifdim\dimexpr\ht\titlebox+\dp\titlebox\relax>#2\relax
    \makebox[#1][l]{\resizebox{!}{#2}{\usebox{\titlebox}}}%
  \else
    \usebox{\titlebox}%
  \fi
}
%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Header and footer for fancy pages
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\pagestyle{fancy}

\fancyhead{}
% Adding CUI to header if defined.
\chead{%
  \if@cuidefined%
    \makebox[\textwidth][c]{\textbsf{\@cuiCat}}
  \fi%
}
% Adding restricted to footer only if is defined w/o CUI.
\fancyfoot{}
\cfoot{%
  \if@cuidefined%
    \relax%
  \else\if@restrictdefined%
    \@restrictfootwarning{\@restrict}%
  \fi\fi%
  \thepage{}%
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Header and footer for plain pages (i.e., most of the document)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\fancypagestyle{plain}

\fancyhead{}
% Adding CUI to header if defined.
\chead{%
 \if@cuidefined%
   \makebox[\textwidth][c]{\textbsf{\@cuiCat}}%
 \fi%
}
% Adding restricted to footer only if is defined w/o CUI.
\cfoot{%
  \if@cuidefined%
    \relax%
  \else\if@restrictdefined%
    \@restrictfootwarning{\@restrict}%
  \fi\fi%
  \thepage{}%
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% BEGIN COVER OPTIONS FOR DIFFERENT REPORT TYPES
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\newcommand{\headlinecolor}{\normalcolor}
\RequirePackage{xcolor}
\definecolor{slcolor}{HTML}{882B21}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% TECHNICAL MEMO (TM) OPTION
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\if@tm % If the tm option is set in the report, we do the following:
%
\def\makecoverpage{%
\newgeometry{top=0.25in,bottom=0.25in,right=1.00in,left=1.00in}

\begin{titlepage}
\thispagestyle{coverpage}
\ThisULCornerWallPaper{1.0}{luggage/TM-front-cover-background.jpg}%

% Added for CUI (remains blank if CUI is undefined)
\printcui

%% REPORT NUMBER %%
\vspace*{0.5\baselineskip plus 1\baselineskip}
\begin{minipage}{\textwidth}
\flushleft
\textcolor{ornlgreen}{\large\textbsf{\@reportnum}} \\
\textcolor{ornlgreen}{\large\textbsf{}}
\end{minipage}%

%% TITLE %%
%\begin{minipage}[c][1in][c]{\textwidth} % Maybe someday this will work?
%  \fittitle[\textwidth]{0.60in}
%\end{minipage}

%% TITLE %%
\begin{minipage}[c][1in][c]{\textwidth}
  \fittitle[\textwidth]{0.60in}
\end{minipage}

\vspace{3.50in}

%%% AUTHOR AND DATE %%%
\begin{minipage}[c][3in][t]{2.5in}%
\large\sffamily % Sets font to sans serif
\printauthors % Prints authors
\vspace*{1\baselineskip \@plus 1\baselineskip \@minus 1\baselineskip} % Adds vertical space
\large\textbsf{\@date}% Prints date
\end{minipage}%
%
%%% NOTICES %%%
% If restrict and draft, show restrict + draft
% If restrict and not draft, show restrict
% If not restrict and draft, show draft
% If not restrict and not draft, show ``approved for public release"
%
\begin{minipage}[c][3.05in][c]{4.00in}%
% Check if document is a draft to determine boxed notices.
\if@reportdraft
  \if@cradaprotecteddefined
    % Do nothing if cradaprotected is defined
  \else
    \if@cuidefined
      \if@cradadefined
        % CUI is defined AND CRADA is defined
        \begin{center}
        \textbsf{\normalsize CRADA draft. Document has not been reviewed and approved for public release.}%
        \end{center}
        \vspace{1em}
      \else
        % CUI is defined but CRADA is NOT defined
        \begin{center}
        \textbsf{\normalsize Draft. Document has not been reviewed and approved for public release.}%
        \end{center}
        \vspace{1em}
      \fi
    \else
      % CUI is NOT defined
      \begin{center}
      \textbsf{\normalsize Draft. Document has not been reviewed and approved for public release.}%
      \end{center}
      \vspace{1em}
    \fi
  \fi
\fi

% Notices for front cover.
\PrintNotices

% Ensure restricted, CRADA, CRADA protected, and CUI documents are *not* marked for public release
% if the document is *not* marked as draft.
\PublicRelease

% Export control notice. Prints if \export is defined in document. Remains blank if not.
\printExport
\end{minipage}

%%% AFFILIATION BLOCK %%%
\begin{minipage}[c][1in][t]{2.5in}%
\IfFileExists{affil-patch.tex}{% Use responsibly.
\vspace*{1\baselineskip \@plus 1\baselineskip \@minus 1\baselineskip} % Adds vertical space
\def\and{\\}% New line between affiliations
  \setlength\tabcolsep{0pt}%
  \maxsizebox*{1.95in}{0.95in}{% Restricting size of affiliation box.
    \small% We want these entries to be smaller.
    \textsf{% Sans Serif
    \begin{tabular}[t]{l}%
      \@affiliation% Prints affiliations
    \end{tabular}
    }
  }
}{}
\end{minipage}%

\vspace{0.60in}
\noindent{\footnotesize\textbsf{ORNL is managed by UT-Battelle LLC for the US~Department of Energy}}
% Footers are now deprecated per PH and KJ. 02/05/2026/STC
%\\
%\printcrada
% Added for restrict (remains blank if \restrict is undefined)
%\printrestrict
%\vspace{-0.10in}
% Added for CUI-EC (remains blank if \cui is undefined)
% \printcui

\end{titlepage}
\restoregeometry
}%

% Create back cover page for TM
\newcommand\backmatter{%
  \clearpage%
  \thispagestyle{plain}%
  \setcounter{page}{0}%
  \renewcommand\thepage{Back cover}%
\begin{titlepage}
  \ThisULCornerWallPaper{1.0}{luggage/TM-back-cover-background.jpg}%
% Added for CUI (remains blank if CUI is undefined)
\printcui

\rule{0pt}{0pt}

\vspace{\fill}

% Footers are now deprecated per PH and KJ. 02/05/2026/STC
% Added for CUI (remains blank if CUI is undefined)
%\printcui
%\begin{center}
%\printcrada
%\end{center}
% Added for restrict (remains blank if \restrict is undefined)
%\printrestrict

\end{titlepage}

}%

\fi % End conditionals for tm option.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% SPONSOR REPORT (SPR) OPTION
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\if@spr % If the spr option is set in the report, we do the following:
%
\def\makecoverpage{%
\newgeometry{top=0.25in,bottom=0.25in,right=1.00in,left=1.00in}

\begin{titlepage}
\thispagestyle{coverpage}
\ThisULCornerWallPaper{1.0}{luggage/SPR-front-cover-background.jpg}%

% Added for CUI (remains blank if CUI is undefined)
\printcui

%% REPORT NUMBER %%
\vspace*{0.5\baselineskip plus 1\baselineskip}
\begin{minipage}{\textwidth}
\flushleft
\textcolor{ornlgreen}{\large\textbsf{\@reportnum}} \\
\textcolor{ornlgreen}{\large\textbsf{\@sponsornum}}
\end{minipage}%

%% TITLE %%
\begin{minipage}[c][1in][c]{\textwidth}
  \fittitle[\textwidth]{0.60in}
\end{minipage}

\vspace{3.25in}

%%% AUTHOR AND DATE %%%
\begin{minipage}[c][3in][t]{2.5in}%
\large\sffamily%
\printauthors% Prints authors
\vspace*{1\baselineskip \@plus 1\baselineskip \@minus 1\baselineskip}
\normalsize\textbsf{\@date}% Prints date
\end{minipage}%
%
%%% NOTICES %%%
% If restrict and draft, show restrict + draft
% If restrict and not draft, show restrict
% If not restrict and draft, show draft
% If not restrict and not draft, show ``approved for public release"
%
\begin{minipage}[c][3.75in][c]{4.00in}%
% Check if document is a draft to determine boxed notices.
\if@reportdraft
  \if@cradaprotecteddefined
    % Do nothing if cradaprotected is defined
  \else
    \if@cuidefined
      \if@cradadefined
        % CUI is defined AND CRADA is defined
        \begin{center}
        \textbsf{\normalsize CRADA draft. Document has not been reviewed and approved for public release.}%
        \end{center}
        \vspace{1em}
      \else
        % CUI is defined but CRADA is NOT defined
        \begin{center}
        \textbsf{\normalsize Draft. Document has not been reviewed and approved for public release.}%
        \end{center}
        \vspace{1em}
      \fi
    \else
      % CUI is NOT defined
      \begin{center}
      \textbsf{\normalsize Draft. Document has not been reviewed and approved for public release.}%
      \end{center}
      \vspace{1em}
    \fi
  \fi
\fi

% Notices for front cover.
\PrintNotices

% Ensure restricted, CRADA protected, and CUI documents are *not* marked for public release
% if the document is *not* marked as draft.
\PublicRelease

% Export control notice. Prints if \export is defined in document. Remains blank if not.
\printExport

  \vspace{0.15in}

\begin{center}
\if@SponsorLogoOnedefined{
\noindent\includegraphics[width=1.25in]{\@SponsorLogoOne}\hspace{0.05\textwidth}
}\else\fi
\if@SponsorLogoTwodefined{
\noindent\includegraphics[width=1.25in]{\@SponsorLogoTwo}
}\else\fi
\end{center}

\end{minipage}%

%%% AFFILIATION BLOCK %%%
\begin{minipage}[c][1in][t]{2.5in}%
\vspace*{1\baselineskip \@plus 1\baselineskip \@minus 1\baselineskip} % Adds vertical space
\def\and{\\}% New line between affiliations
  \setlength\tabcolsep{0pt}%
  \maxsizebox*{1.95in}{0.95in}{% Restricting size of affiliation box.
    \small% We want these entries to be smaller.
    \textsf{% Sans Serif
    \begin{tabular}[t]{l}%
      \@affiliation% Prints affiliations
    \end{tabular}
    }
  }
{}
\end{minipage}%


%\vspace{-0.15in}
%
%\begin{center}
%\if@SponsorLogoOnedefined{
%\noindent\includegraphics[width=1.25in]{\@SponsorLogoOne}\hspace{0.05\textwidth}
%}\else\fi
%\if@SponsorLogoTwodefined{
%\noindent\includegraphics[width=1.25in]{\@SponsorLogoTwo}
%}\else\fi
%\end{center}
%
%\vspace{-0.10in}


\vspace{0.25in}

\noindent{\footnotesize\textbsf{ORNL is managed by UT-Battelle LLC for the US~Department of Energy}}
% Footers are now deprecated per PH and KJ. 02/05/2026/STC
%\\
%\printcrada
% Added for restrict (remains blank if \restrict is undefined)
% \vspace{-0.1in}\printrestrict %\vspace{-2em}
% Added for CUI (remains blank if \cui is undefined)
%\printcui  


\end{titlepage}
\restoregeometry
}%

% Create back cover page for SPR
\newcommand\backmatter{%
  \clearpage%
  \thispagestyle{plain}%
  \setcounter{page}{0}%
  \renewcommand\thepage{Back cover}%
\begin{titlepage}
  \ThisULCornerWallPaper{1.0}{luggage/SPR-back-cover-background.jpg}%
% Added for CUI (remains blank if CUI is undefined)
\printcui

\rule{0pt}{0pt}

\vspace{\fill}

% Footers are now deprecated per PH and KJ. 02/05/2026/STC
%\begin{center}
% Added for CUI (remains blank if CUI is undefined)
%\printcui
%\printcrada
% Added for restrict (remains blank if \restrict is undefined)
%\printrestrict
%\end{center}

\end{titlepage}

}%
\fi % End conditionals for the spr option.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% ORNL LETTER (LTR) OPTION
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\if@ltr % If the ltr option is set in the report, we do the following:
%
  \AtBeginDocument{% First, we suppress the front matter commands for LTR.
    \renewcommand{\tableofcontents}{\relax}%
    \renewcommand{\listoftables}{\relax}%
    \renewcommand{\listoffigures}{\relax}%
    \renewcommand{\printacronyms}{\relax}%
  }
%
\def\makecoverpage{% Next we set the cover page.
\newgeometry{top=0.35in,bottom=0.35in,right=0.5in,left=1.25in}

\begin{titlepage}
\thispagestyle{coverpage}
\ThisULCornerWallPaper{1.0}{luggage/LTR-front-cover-background.png}%

% Added for CUI (remains blank if CUI is undefined)
\printcui

%% REPORT NUMBER %%
\vspace*{0.5\baselineskip plus 1\baselineskip}
\begin{minipage}{\textwidth}
\raggedright
\textcolor{ornlgreen}{\large\textbsf{\@reportnum}}
\end{minipage}%

\vspace*{0.05\baselineskip plus 0.05fill}

%% TITLE %%
\begin{minipage}[c][1in][c]{\textwidth}
  \fittitle[\textwidth]{0.60in}
\end{minipage}

\vspace*{1\baselineskip plus 1\baselineskip minus 1\baselineskip}

%%% GRADIENT LINE %%%
%\hspace*{-1.25in}\includegraphics[width=8.5in, height=0.35in]{luggage/ltr-gradient-bar.png}%
\vspace*{3.25in} % Adds space between gradient bar and author block and draft notice.

%%% AUTHOR AND DATE %%%
\begin{minipage}[c][4in][t]{2.75in}%
  \large\sffamily%
  \printauthors% Prints authors
\vspace*{1\baselineskip \@plus 1\baselineskip \@minus 1\baselineskip}% Adds space between authors and date
  \normalsize\textbsf{\@date}% Prints date
\end{minipage}%
%
\begin{minipage}[c][4in][t]{4.00in}%
% Check if document is a draft to determine boxed notices.
\if@reportdraft{
\begin{center}
  \textbsf{\normalsize Draft. Document has not been reviewed and approved for public release.}%
\end{center}
\vspace{2em}
}
\fi

%%% NOTICES %%%
% If restrict and draft, show restrict + draft
% If restrict and not draft, show restrict
% If not restrict and draft, show draft
% If not restrict and not draft, show ``approved for public release"

% Checking for restricted first.
\if@cuidefined{% No CUI notice needed, so do nothing.
}\else % Otherwise, check for restrict.
\if@restrictdefined{% If restrict is defined in document, then print box.
\begin{center}
\printrestrict%
\end{center}
\vspace{2em}
}
\fi
\fi

% Ensure restricted and CUI documents are *not* marked for public release
% if the document is *not* marked as draft.
\PublicRelease

% Export control notice. Prints if \export is defined in document. Remains blank if not.
\printExport

\end{minipage}

\vspace*{0pt \@plus 1fill}

\begin{minipage}{\textwidth}%
    \hspace*{-0.25in}\textcolor{white}{{\textbsf{\footnotesize ORNL is managed BY UT-Battelle LLC for the US~Department of Energy}}}
% Footers are now deprecated per PH and KJ. 02/05/2026/STC
%\if@restrictdefined{
%	\vspace{-1.5em}
%	\textcolor{white}{\printrestrict}%
%}
%\else
%\fi%

\end{minipage}%
\end{titlepage}
\restoregeometry
}%


% Create back cover page for LTR
\newcommand\backmatter{%
  \clearpage%
  \thispagestyle{plain}%
  \setcounter{page}{0}%
  \renewcommand\thepage{Back cover}%
\begin{titlepage}
  \ThisULCornerWallPaper{1.0}{luggage/LTR-back-cover-background.jpg}%
% Added for CUI (remains blank if CUI is undefined)
\printcui

\rule{0pt}{0pt}

\vspace{\fill}

% Footers are now deprecated per PH and KJ. 02/05/2026/STC
% Added for CUI (remains blank if CUI is undefined)
%\printcui
%\printcrada
% Added for restrict (remains blank if \restrict is undefined)
%\printrestrict

\end{titlepage}
}
\fi % End conditionals for the ltr option.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% END COVER OPTIONS FOR DIFFERENT REPORT TYPES
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% OSTI NOTICE PAGE
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% Email URL command
\newcommand{\email}[1]{\href{mailto:#1}{#1}}

% Create page
\def\makeostipage{%
\begin{titlepage}

% Added for CUI (remains blank if CUI is undefined)
\printcui


\vspace*{.5in}

  \centering\sffamily\small
  \fbox{\parbox{5.61in}{%
    \begin{center}
      \textbf{DOCUMENT AVAILABILITY}
    \end{center}

\textbf{\textit{Online Access:}} US Department of Energy (DOE) reports produced
after 1991 and a growing number of pre-1991 documents are available free via
\href{https://www.osti.gov/}{https://www.osti.gov/}.  \\

The public may also search the National Technical Information Service's
\href{https://ntrl.ntis.gov/NTRL/}{National Technical Reports Library (NTRL)}
for reports not available in digital format. \\

DOE and DOE contractors should contact DOE's Office of Scientific and Technical
Information (OSTI) for reports not currently available in digital format: \\

\begin{quote}
US Department of Energy \\
Office of Scientific and Technical Information \\
PO Box 62 \\
Oak Ridge, TN 37831-0062 \\
\textbf{\textit{Telephone:}} (865) 576-8401 \\
\textbf{\textit{Fax:}} (865) 576-5728 \\
\textbf{\textit{Email:}}  \href{mailto:reports@osti.gov}{reports@osti.gov} \\
\textbf{\textit{Website:}} \href{https://www.osti.gov/}{https://www.osti.gov/} \\
\end{quote}

}}

\vspace{0.5in}

\fbox{\parbox{4in}{
This report was prepared as an account of work sponsored by an agency of the
United States Government. Neither the United States Government nor any agency
thereof, nor any of their employees, makes any warranty, express or implied, or
assumes any legal liability or responsibility for the accuracy, completeness, or
usefulness of any information, apparatus, product, or process disclosed, or
represents that its use would not infringe privately owned rights. Reference
herein to any specific commercial product, process, or service by trade name,
trademark, manufacturer, or otherwise, does not necessarily constitute or imply
its endorsement, recommendation, or favoring by the United States Government or
any agency thereof. The views and opinions of authors expressed herein do not
necessarily state or reflect those of the United States Government or any agency
thereof.}}

\vspace*{0.5in}

% Added for CUI (remains blank if CUI is undefined)
%\printcui
% Added for restrict (remains blank if \restrict is undefined)
\printrestrict

\end{titlepage}
}


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% CRADA INSTRUCTIONS PAGE
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\newcommand\makecradapage{%
  \if@tm
    \@makecradapageaux
  \else
    \if@spr
      \@makecradapageaux
    \fi
  \fi
}

\newcommand\@makecradapageaux{%
  \if@cradadefined
    \begin{titlepage}
    \pagestyle{coverpage}
    \ifpdf
      % This part will only be included if using PDFTeX
      \IfFileExists{ORNL-851-complete.jpg}
        {% File exists
          \begin{figure}[ht]
          \centering
          \includegraphics[width=\textwidth, height=\textheight, keepaspectratio]{ORNL-851-complete.jpg}
          \end{figure}
        }
        {% File does not exist
          \noindent
          \section*{ORNL-851 Form}
          Once your CRADA document is final, please fill out the \texttt{ORNL-851.pdf}
          form that resides in this repository. You can also download \texttt{ORNL-851.pdf} from the
          \href{https://ornl.sharepoint.com/sites/forms/ornl/Forms/Forms\%20View.aspx}{
          ORNL forms webpage}.
          \subsection*{Instructions for Overleaf/ShareLaTeX}
          \begin{enumerate}
          \item Download \texttt{ORNL-851.pdf} from your project or from the
          \href{https://ornl.sharepoint.com/sites/forms/ornl/Forms/Forms\%20View.aspx}{ORNL
                forms webpage}.
          \item Open the form in Adobe Acrobat and fill it out.
          \item Once complete, in Acrobat select \textsf{File} $\rightarrow$ \textsf{Export
                to...} $\rightarrow$ \textsf{Image} $\rightarrow$ \textsf{JPEG}.
          \item Save the file as \texttt{ORNL-851-complete.jpg}.
          \item Upload \texttt{ORNL-851-complete.jpg} to your Overleaf/ShareLaTeX
                project's main path.
          \item Recompile document.
          \end{enumerate}
          Your completed form should appear on the third page, thereby replacing
          these instructions.
          \subsection*{Instructions for Local/Repository}
          \begin{enumerate}
          \item Navigate to your project's main path.
          \item Find and open \texttt{ORNL-851.pdf} or download
                a copy from the
          \href{https://ornl.sharepoint.com/sites/forms/ornl/Forms/Forms\%20View.aspx}{ORNL
                forms webpage}.
          \item Open the form in Adobe Acrobat and fill it out.
          \item Once complete, in Acrobat select \textsf{File} $\rightarrow$ \textsf{Export
                to...} $\rightarrow$ \textsf{Image} $\rightarrow$ \textsf{JPEG}.
          \item Save the file as \texttt{ORNL-851-complete.jpg} in your project's
                main path.
          \item Recompile document.
          \end{enumerate}
          Your completed form should appear on the third page, thereby replacing
          these instructions.
          \begin{figure}[ht]
          \centering
          \begin{minipage}{0.5\textwidth}
          \centering
          \includegraphics[width=8cm,height=5.5cm]{luggage/form-ORNL-851-instructions.png}
          \caption*{Export JPEG from Acrobat.}
          \end{minipage}%
          \begin{minipage}{0.5\textwidth}
          \centering
          \includegraphics[width=8cm,height=5.5cm]{luggage/upload.png}
          \caption*{Upload button in Overleaf/ShareLaTeX.}
          \end{minipage}
          \end{figure}
        }
    \else
      % This part will only be included if not using PDFTeX
      \noindent
      \textbf{This document requires PDFLaTeX.}
    \fi
    \end{titlepage}
    \clearpage
  \fi
}
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% TITLE
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\newcommand\maketitlepage{%
\begin{titlepage}
\setcounter{page}{2}%

% Added for CUI (remains blank if CUI is undefined)
\printcui

%%% REPORT NUMBER %%%
\raggedleft{\large\textbf{\@reportnum}}
\vspace{1in}

%%% DIVISION %%%
\centering\@division
\vspace{\stretch{1}}

\begin{minipage}{\textwidth}%
\begin{center}
  \Large\textbf{%
    \MakeUppercase{\@title}
  }
\end{center}
\end{minipage}%

\vspace{\stretch{1}}

%%% AUTHOR %%%
\maxsizebox*{!}{3.75in}{%
    \renewcommand{\affilnum}[1]{}% Strips affilnum by redefining as simply a new line
    \def\and{\tabularnewline}%
    \begin{tabular}[t]{c}%
      \@author
    \end{tabular}%
}

\vspace{\stretch{.5}}

% Date Published
\@date

\vspace{\stretch{.5}}

Prepared by \\
OAK RIDGE NATIONAL LABORATORY \\
Oak Ridge, TN 37831 \\
managed by \\
UT-BATTELLE LLC \\
for the \\
US DEPARTMENT OF ENERGY \\
under contract DE-AC05-00OR22725

\vspace{\stretch{.5}}

% Added for CUI (remains blank if CUI is undefined)
%\printcui
% Added for restrict (remains blank if \restrict is undefined)
\printrestrict

\end{titlepage}%
} % end \maketitlepage

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% FRONT MATTER
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\newif\if@mainmatter
\@mainmattertrue
\def\@cleariffrontmatter{\if@mainmatter\relax\else{\clearpage}\fi}
\def\@cleardbliffrontmatter{\if@mainmatter\relax\else{\cleardoublepage}\fi}

\newcommand\frontmatter{%
  \@mainmatterfalse%
  \renewcommand\and{\\}
  \renewcommand\thepage{Front cover}%
  \makecoverpage%
  \pagenumbering{roman}%
  \setcounter{page}{1}%
  \makeostipage%
  \makecradapage% NEW: Adds CRADA instructions to TM.
  \maketitlepage%
  \cleardoublepage
  \setcounter{page}{3}%
}

% Adds foreword environment.
\newenvironment{foreword}{%
	\addcontentsline{toc}{section}{\ornltmforewordname}
	\phantomsection
  \section*{\ornltmforewordname}%
}

% Abstract gets a new page if it's in the front matter; otherwise it's just at
% the top of the page.
\renewenvironment{abstract}{%
\if@mainmatter\relax\else
  \cleardoublepage
	\pagenumbering{arabic}
	\setcounter{page}{1}
\fi
	\addcontentsline{toc}{section}{\ornltmabstractname}
	\phantomsection
  \section*{\ornltmabstractname}%
}{}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% TABLE OF CONTENTS, LIST OF FIGURES, LIST OF TABLES
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% Clear the page before TOC if it is in the ``front matter''
\AtBeginDocument{%
\let\@origcfttoc\tableofcontents
\renewcommand\tableofcontents{%
\@cleardbliffrontmatter
\@origcfttoc%
}%
}

% Lists should have plain numbering if in the front matter
\renewcommand\@cfttocstart{%
  \if@mainmatter%
    \relax%
  \else%
    \thispagestyle{plain}%
  \fi%
}
% Lists should clear the page after if in front matter
\renewcommand\@cfttocfinish{\@cleariffrontmatter}

% Add section titles for figures/tables
\renewcommand\cftlofprehook{%
\phantomsection\addcontentsline{toc}{section}{\ornltmlofname}%
}
\renewcommand\cftlotprehook{%
\phantomsection\addcontentsline{toc}{section}{\ornltmlotname}%
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% MAIN MATTER
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\newcommand\mainmatter{%
  \cleardoublepage%
  \@mainmattertrue%
  \pagenumbering{arabic}%
  % Don't break the first section in order to allow ``mainmatter'' abstracts to
  % work correctly.
  \renewcommand{\sectionbreak}{\renewcommand\sectionbreak\cleardoublepage}
}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% CAPTION STYLES
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\RequirePackage[font=bf,labelsep=period,justification=centering]{caption}

% Caption with more than one sentence: the first sentence is the first argument,
% the rest are the second. This allows table of contents to just show the first
% sentence but display the whole thing in the text. It also clears the boldface
% from the second part. 
\newcommand\longcaption[2]{\caption[#1]{#1 \normalfont #2}}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% BACK MATTER
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Because each report type now has its own background image, the backmatter
% command is now handled in the report variables/conditionals.

\iffalse 
\newcommand\backmatter{%
  \clearpage%
  \thispagestyle{plain}%
  \setcounter{page}{0}%
  \renewcommand\thepage{Back cover}%
\begin{titlepage}
% Added for CUI (remains blank if CUI is undefined)
\printcui


  \rule{0pt}{0pt}

  \vspace{\fill}

  \textcolor{ornlgreen}{\rule{\textwidth}{.5pt}}
  
% Added for CUI (remains blank if CUI is undefined)
%\printcui
\printcrada
% Added for restrict (remains blank if \restrict is undefined)
\printrestrict

\end{titlepage}
}
\fi

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\endinput
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% end of Exnihilo/environment/latex/ornltm.cls
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
